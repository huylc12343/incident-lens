"""Validated multipart upload storage for incident inputs."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from src.models.api import IncidentUploadResponse

VIDEO_EXTENSIONS = {".avi", ".mkv", ".mov", ".mp4", ".webm"}
LOG_EXTENSIONS = {".csv"}
CHUNK_SIZE = 1024 * 1024


class IncidentUploadError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IncidentUploadService:
    def __init__(self, *, upload_dir: str, max_video_bytes: int, max_log_bytes: int) -> None:
        if not upload_dir.strip() or min(max_video_bytes, max_log_bytes) <= 0:
            raise ValueError("upload directory and positive size limits are required")
        self._upload_dir = Path(upload_dir).resolve()
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        self._max_video_bytes = max_video_bytes
        self._max_log_bytes = max_log_bytes

    async def save(self, video: UploadFile, log: UploadFile | None = None) -> IncidentUploadResponse:
        saved: list[Path] = []
        try:
            video_path = await self._save_file(video, "video", VIDEO_EXTENSIONS, self._max_video_bytes)
            saved.append(video_path)
            log_path = None
            if log is not None:
                log_path = await self._save_file(log, "log", LOG_EXTENSIONS, self._max_log_bytes)
                saved.append(log_path)
            return IncidentUploadResponse(
                video_uri=str(video_path),
                log_uri=str(log_path) if log_path is not None else None,
            )
        except Exception:
            for path in saved:
                path.unlink(missing_ok=True)
            raise
        finally:
            await video.close()
            if log is not None:
                await log.close()

    async def _save_file(
        self,
        upload: UploadFile,
        label: str,
        allowed_extensions: set[str],
        max_bytes: int,
    ) -> Path:
        original_name = Path(upload.filename or "").name
        extension = Path(original_name).suffix.lower()
        if not original_name or extension not in allowed_extensions:
            allowed = ", ".join(sorted(allowed_extensions))
            raise IncidentUploadError("UPLOAD_FILE_TYPE_INVALID", f"{label} file must use: {allowed}")
        safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(original_name).stem).strip("._") or label
        destination = self._upload_dir / f"{uuid4().hex}-{safe_stem}{extension}"
        total = 0
        try:
            with destination.open("xb") as output:
                while chunk := await upload.read(CHUNK_SIZE):
                    total += len(chunk)
                    if total > max_bytes:
                        raise IncidentUploadError("UPLOAD_FILE_TOO_LARGE", f"{label} file exceeds the size limit")
                    output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if total == 0:
            destination.unlink(missing_ok=True)
            raise IncidentUploadError("UPLOAD_FILE_EMPTY", f"{label} file is empty")
        return destination
