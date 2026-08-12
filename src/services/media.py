"""Deterministic local video probing, normalization, and frame sampling."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from src.models.incidents import IncidentWindow, NativeVideoMetadata, TimestampedFrame, VideoSequenceManifest


class MediaServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NormalizedVideoArtifact:
    uri: str
    metadata: NativeVideoMetadata


class MediaService:
    def __init__(self, *, command_timeout_s: float = 120.0) -> None:
        if command_timeout_s <= 0:
            raise ValueError("command_timeout_s must be positive")
        self._command_timeout_s = command_timeout_s
        self._ffmpeg = shutil.which("ffmpeg") or get_ffmpeg_exe()
        self._ffprobe = shutil.which("ffprobe")

    async def probe_video(self, video_uri: str) -> NativeVideoMetadata:
        source = _existing_file(video_uri)
        if not self._ffprobe:
            return await self._probe_with_ffmpeg(source)
        stdout, _ = await self._run_command(
            self._ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate:format=duration,size",
            "-of",
            "json",
            str(source),
        )
        try:
            payload = json.loads(stdout)
            stream = payload["streams"][0]
            file_format = payload["format"]
            duration_s = float(file_format["duration"])
            width = int(stream["width"])
            height = int(stream["height"])
            fps = _parse_frame_rate(stream["avg_frame_rate"])
            size_bytes = int(file_format.get("size") or source.stat().st_size)
            return NativeVideoMetadata(
                duration_s=duration_s,
                width=width,
                height=height,
                fps=fps,
                size_bytes=size_bytes,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise MediaServiceError("VIDEO_PROBE_INVALID", "ffprobe returned invalid video metadata") from exc

    async def _probe_with_ffmpeg(self, source: Path) -> NativeVideoMetadata:
        _, stderr = await self._run_command(
            self._ffmpeg,
            "-hide_banner",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        )
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
        video_line = next((line for line in stderr.splitlines() if "Video:" in line), "")
        size_match = re.search(r"\b(\d{2,5})x(\d{2,5})\b", video_line)
        fps_match = re.search(r"\b(\d+(?:\.\d+)?) fps\b", video_line)
        if not duration_match or not size_match or not fps_match:
            raise MediaServiceError("VIDEO_PROBE_INVALID", "ffmpeg returned invalid video metadata")
        hours, minutes, seconds = duration_match.groups()
        duration_s = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        return NativeVideoMetadata(
            duration_s=duration_s,
            width=int(size_match.group(1)),
            height=int(size_match.group(2)),
            fps=float(fps_match.group(1)),
            size_bytes=source.stat().st_size,
        )

    async def normalize_video(
        self,
        video_uri: str,
        output_uri: str,
        *,
        width: int,
        height: int,
        fps: float,
        codec: str,
        pixel_format: str,
        max_output_bytes: int,
        max_duration_s: float = 60.0,
    ) -> NormalizedVideoArtifact:
        source = _existing_file(video_uri)
        probe = await self.probe_video(str(source))
        if probe.duration_s > max_duration_s:
            raise MediaServiceError(
                "VIDEO_DURATION_EXCEEDED",
                f"video duration {probe.duration_s:.3f}s exceeds {max_duration_s:.3f}s",
            )
        if min(width, height, fps, max_output_bytes) <= 0:
            raise ValueError("normalization dimensions, fps, and byte limit must be positive")

        output = Path(output_uri).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}"
        )
        await self._run_command(
            self._ffmpeg,
            "-y",
            "-i",
            str(source),
            "-vf",
            video_filter,
            "-c:v",
            codec,
            "-pix_fmt",
            pixel_format,
            "-movflags",
            "+faststart",
            str(output),
        )
        if not output.is_file():
            raise MediaServiceError("VIDEO_NORMALIZATION_FAILED", "ffmpeg did not create an output video")
        if output.stat().st_size > max_output_bytes:
            output.unlink(missing_ok=True)
            raise MediaServiceError("VIDEO_OUTPUT_TOO_LARGE", "normalized video exceeds configured byte limit")

        metadata = await self.probe_video(str(output))
        return NormalizedVideoArtifact(uri=str(output), metadata=metadata)

    async def cut_incident_clip(
        self,
        video_uri: str,
        output_uri: str,
        *,
        window: IncidentWindow,
        codec: str,
        pixel_format: str,
        min_duration_s: float = 5.0,
        pre_roll_s: float = 1.0,
        post_roll_s: float = 2.0,
    ) -> NormalizedVideoArtifact:
        source = _existing_file(video_uri)
        probe = await self.probe_video(str(source))
        if window.t_end > probe.duration_s:
            raise MediaServiceError("CLIP_WINDOW_OUT_OF_RANGE", "incident window exceeds video duration")
        clip_start, clip_end = _expanded_clip_bounds(
            window,
            source_duration_s=probe.duration_s,
            min_duration_s=min_duration_s,
            pre_roll_s=pre_roll_s,
            post_roll_s=post_roll_s,
        )
        output = Path(output_uri).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        await self._run_command(
            self._ffmpeg,
            "-y",
            "-ss",
            str(clip_start),
            "-i",
            str(source),
            "-t",
            str(clip_end - clip_start),
            "-c:v",
            codec,
            "-pix_fmt",
            pixel_format,
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output),
        )
        if not output.is_file():
            raise MediaServiceError("INCIDENT_CLIP_FAILED", "ffmpeg did not create the incident clip")
        return NormalizedVideoArtifact(uri=str(output), metadata=await self.probe_video(str(output)))

    async def sample_frames(
        self,
        video_uri: str,
        output_dir: str,
        *,
        fps: float,
        width: int,
        height: int,
        image_format: str,
        jpeg_quality: int,
        max_frames: int,
        start_s: float = 0.0,
        end_s: float | None = None,
    ) -> VideoSequenceManifest:
        source = _existing_file(video_uri)
        probe = await self.probe_video(str(source))
        if fps <= 0 or width <= 0 or height <= 0 or max_frames <= 0:
            raise ValueError("frame sampling parameters must be positive")
        if start_s < 0 or start_s >= probe.duration_s:
            raise ValueError("start_s must be within the video duration")
        clip_end = probe.duration_s if end_s is None else end_s
        if clip_end <= start_s or clip_end > probe.duration_s:
            raise ValueError("end_s must be after start_s and within the video duration")
        if image_format not in {"jpeg", "png"}:
            raise ValueError("image_format must be jpeg or png")
        if not 1 <= jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be between 1 and 100")

        destination = Path(output_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        extension = "jpg" if image_format == "jpeg" else "png"
        output_pattern = destination / f"frame-%06d.{extension}"
        duration_s = clip_end - start_s
        video_filter = (
            f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
        command = [
            self._ffmpeg,
            "-y",
            "-ss",
            str(start_s),
            "-i",
            str(source),
            "-t",
            str(duration_s),
            "-vf",
            video_filter,
            "-frames:v",
            str(max_frames),
        ]
        if image_format == "jpeg":
            command.extend(["-q:v", str(_jpeg_quality_to_ffmpeg(jpeg_quality))])
        command.append(str(output_pattern))
        await self._run_command(*command)

        frame_paths = sorted(destination.glob(f"frame-*.{extension}"))[:max_frames]
        if not frame_paths:
            raise MediaServiceError("FRAME_SAMPLING_FAILED", "ffmpeg did not produce any frames")
        frames = []
        for index, path in enumerate(frame_paths):
            timestamp_s = min(start_s + (index / fps), clip_end)
            frames.append(
                TimestampedFrame(
                    frame_id=path.stem,
                    sequence_index=index,
                    timestamp_s=timestamp_s,
                    delta_from_previous_s=0.0 if index == 0 else 1 / fps,
                    image_uri=str(path),
                    mime_type="image/jpeg" if image_format == "jpeg" else "image/png",
                )
            )
        return VideoSequenceManifest(frames=frames, source_video_uri=str(source), duration_s=probe.duration_s)

    async def _run_command(self, *command: str) -> tuple[str, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._command_timeout_s)
        except TimeoutError as exc:
            if "process" in locals():
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
                with suppress(ProcessLookupError):
                    await process.communicate()
            raise MediaServiceError("MEDIA_COMMAND_TIMEOUT", "media command timed out") from exc
        except OSError as exc:
            raise MediaServiceError("MEDIA_COMMAND_FAILED", str(exc)) from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise MediaServiceError("MEDIA_COMMAND_FAILED", detail or "media command failed")
        return stdout.decode("utf-8"), stderr.decode("utf-8", errors="replace")


def _existing_file(uri: str) -> Path:
    path = Path(uri).resolve()
    if not path.is_file():
        raise MediaServiceError("MEDIA_NOT_FOUND", f"media file does not exist: {uri}")
    return path


def _parse_frame_rate(value: str) -> float:
    numerator, separator, denominator = value.partition("/")
    if not separator:
        rate = float(numerator)
    else:
        rate = float(numerator) / float(denominator)
    if rate <= 0:
        raise ValueError("frame rate must be positive")
    return rate


def _jpeg_quality_to_ffmpeg(quality: int) -> int:
    return max(2, min(31, round(31 - (quality / 100 * 29))))


def _expanded_clip_bounds(
    window: IncidentWindow,
    *,
    source_duration_s: float,
    min_duration_s: float,
    pre_roll_s: float,
    post_roll_s: float,
) -> tuple[float, float]:
    if source_duration_s <= 0 or min_duration_s <= 0:
        raise ValueError("source and minimum clip durations must be positive")
    if pre_roll_s < 0 or post_roll_s < 0:
        raise ValueError("clip roll durations must be non-negative")

    start_s = max(0.0, window.t_start - pre_roll_s)
    end_s = min(source_duration_s, window.t_end + post_roll_s)
    target_duration_s = min(source_duration_s, min_duration_s)
    missing_s = max(0.0, target_duration_s - (end_s - start_s))

    # Prefer later context because incident consequences usually follow the first detected event.
    extend_after_s = min(missing_s, source_duration_s - end_s)
    end_s += extend_after_s
    missing_s -= extend_after_s
    start_s = max(0.0, start_s - missing_s)
    return start_s, end_s
