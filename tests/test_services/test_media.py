import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.models.incidents import IncidentWindow, NativeVideoMetadata
from src.services.media import MediaService, MediaServiceError

SAMPLE_VIDEO = Path("data_mock/data1/front_camera.mp4")


@pytest.mark.asyncio
async def test_run_command_does_not_require_event_loop_subprocess_support(monkeypatch) -> None:
    service = MediaService(command_timeout_s=5)
    received: list[tuple[str, ...]] = []

    async def unsupported_event_loop_subprocess(*args, **kwargs):
        raise AssertionError("event-loop subprocess transport must not be used")

    def run_in_thread(command, **kwargs):
        received.append(tuple(command))
        assert kwargs["timeout"] == 5
        return subprocess.CompletedProcess(command, 0, stdout=b"probe output", stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unsupported_event_loop_subprocess)
    monkeypatch.setattr(subprocess, "run", run_in_thread)

    stdout, stderr = await service._run_command("ffmpeg", "-version")

    assert received == [("ffmpeg", "-version")]
    assert stdout == "probe output"
    assert stderr == ""


@pytest.mark.asyncio
async def test_run_command_maps_threaded_subprocess_timeout(monkeypatch) -> None:
    service = MediaService(command_timeout_s=0.1)

    def time_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", time_out)

    with pytest.raises(MediaServiceError) as exc_info:
        await service._run_command("ffmpeg", "-version")

    assert exc_info.value.code == "MEDIA_COMMAND_TIMEOUT"


@pytest.mark.asyncio
async def test_probe_and_sample_real_video(tmp_path: Path) -> None:
    service = MediaService(command_timeout_s=30)

    metadata = await service.probe_video(str(SAMPLE_VIDEO))
    manifest = await service.sample_frames(
        str(SAMPLE_VIDEO),
        str(tmp_path / "frames"),
        fps=1,
        width=160,
        height=90,
        image_format="jpeg",
        jpeg_quality=80,
        max_frames=3,
        start_s=0,
        end_s=min(metadata.duration_s, 3),
    )

    assert 0 < metadata.duration_s <= 60
    assert metadata.width > 0 and metadata.height > 0
    assert [frame.sequence_index for frame in manifest.frames] == list(range(len(manifest.frames)))
    assert [frame.timestamp_s for frame in manifest.frames] == sorted(frame.timestamp_s for frame in manifest.frames)
    assert all(Path(frame.image_uri).is_file() for frame in manifest.frames)
    assert all(frame.frame_id == Path(frame.image_uri).stem for frame in manifest.frames)


@pytest.mark.asyncio
async def test_normalize_real_video(tmp_path: Path) -> None:
    service = MediaService(command_timeout_s=60)
    output = tmp_path / "normalized.mp4"

    artifact = await service.normalize_video(
        str(SAMPLE_VIDEO),
        str(output),
        width=160,
        height=90,
        fps=5,
        codec="libx264",
        pixel_format="yuv420p",
        max_output_bytes=10_000_000,
    )

    assert output.is_file()
    assert artifact.uri == str(output.resolve())
    assert artifact.metadata.width == 160
    assert artifact.metadata.height == 90
    assert artifact.metadata.fps == pytest.approx(5)
    assert artifact.metadata.size_bytes <= 10_000_000


@pytest.mark.asyncio
async def test_normalize_video_fits_qwen_base64_limit(tmp_path: Path) -> None:
    service = MediaService(command_timeout_s=60)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "qwen-base64.mp4"

    metadata = NativeVideoMetadata(
        duration_s=60,
        width=512,
        height=288,
        fps=15,
        size_bytes=5_000_000,
    )
    service.probe_video = AsyncMock(side_effect=[metadata, metadata])

    async def create_output(*args: str) -> tuple[str, str]:
        Path(args[-1]).write_bytes(b"normalized")
        return "", ""

    service._run_command = AsyncMock(side_effect=create_output)

    artifact = await service.normalize_video(
        str(source),
        str(output),
        width=512,
        height=288,
        fps=15,
        codec="libx264",
        pixel_format="yuv420p",
        max_output_bytes=7_000_000,
    )

    assert artifact.metadata.size_bytes <= 7_000_000
    command = service._run_command.await_args.args
    assert command[command.index("-b:v") + 1] == "700k"
    assert "-an" in command


@pytest.mark.asyncio
async def test_cut_incident_clip_from_real_video(tmp_path: Path) -> None:
    service = MediaService(command_timeout_s=60)
    output = tmp_path / "incident_clip.mp4"

    artifact = await service.cut_incident_clip(
        str(SAMPLE_VIDEO),
        str(output),
        window=IncidentWindow(t_start=6, t0=7.5, t_end=9),
        codec="libx264",
        pixel_format="yuv420p",
    )

    assert output.is_file()
    assert artifact.uri == str(output.resolve())
    assert artifact.metadata.duration_s == pytest.approx(6, abs=0.15)


@pytest.mark.asyncio
async def test_cut_incident_clip_expands_one_second_window(tmp_path: Path) -> None:
    service = MediaService(command_timeout_s=60)

    artifact = await service.cut_incident_clip(
        str(SAMPLE_VIDEO),
        str(tmp_path / "expanded_clip.mp4"),
        window=IncidentWindow(t_start=5, t0=5.5, t_end=6),
        codec="libx264",
        pixel_format="yuv420p",
    )

    assert artifact.metadata.duration_s == pytest.approx(5, abs=0.15)


@pytest.mark.asyncio
async def test_media_service_rejects_missing_input(tmp_path: Path) -> None:
    service = MediaService()

    with pytest.raises(MediaServiceError, match="does not exist") as exc_info:
        await service.probe_video(str(tmp_path / "missing.mp4"))

    assert exc_info.value.code == "MEDIA_NOT_FOUND"


@pytest.mark.asyncio
async def test_cut_incident_clip_rejects_window_outside_video(tmp_path: Path) -> None:
    service = MediaService(command_timeout_s=30)

    with pytest.raises(MediaServiceError) as exc_info:
        await service.cut_incident_clip(
            str(SAMPLE_VIDEO),
            str(tmp_path / "clip.mp4"),
            window=IncidentWindow(t_start=16, t0=18, t_end=20),
            codec="libx264",
            pixel_format="yuv420p",
        )

    assert exc_info.value.code == "CLIP_WINDOW_OUT_OF_RANGE"
