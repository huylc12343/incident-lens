from pathlib import Path
from tempfile import SpooledTemporaryFile

import pytest
from fastapi import UploadFile

from src.main import app
from src.services.uploads import IncidentUploadService


@pytest.mark.asyncio
async def test_upload_endpoint_stores_video_and_optional_log(client, tmp_path: Path) -> None:
    app.state.incident_upload_service = IncidentUploadService(
        upload_dir=str(tmp_path),
        max_log_bytes=1024,
    )
    try:
        response = await client.post(
            "/api/v1/incidents/uploads",
            files={
                "video": ("camera.mp4", b"video-bytes", "video/mp4"),
                "log": ("vehicle.csv", b"timestamp_s,speed_kmh\n0,1\n", "text/csv"),
            },
        )
    finally:
        del app.state.incident_upload_service

    assert response.status_code == 201
    payload = response.json()
    assert Path(payload["video_uri"]).read_bytes() == b"video-bytes"
    assert Path(payload["log_uri"]).read_text().startswith("timestamp_s")


@pytest.mark.asyncio
async def test_upload_service_does_not_limit_video_size(tmp_path: Path) -> None:
    service = IncidentUploadService(
        upload_dir=str(tmp_path),
        max_log_bytes=1024,
    )
    video = b"v" * (2 * 1024 * 1024)
    source = SpooledTemporaryFile(max_size=len(video) + 1)
    source.write(video)
    source.seek(0)
    upload = UploadFile(file=source, filename="camera.mp4")

    result = await service.save(upload)

    assert Path(result.video_uri).stat().st_size == len(video)


@pytest.mark.asyncio
async def test_upload_endpoint_rejects_invalid_log_and_removes_video(client, tmp_path: Path) -> None:
    app.state.incident_upload_service = IncidentUploadService(
        upload_dir=str(tmp_path),
        max_log_bytes=1024,
    )
    try:
        response = await client.post(
            "/api/v1/incidents/uploads",
            files={
                "video": ("camera.mp4", b"video-bytes", "video/mp4"),
                "log": ("notes.txt", b"invalid", "text/plain"),
            },
        )
    finally:
        del app.state.incident_upload_service

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UPLOAD_FILE_TYPE_INVALID"
    assert list(tmp_path.iterdir()) == []
