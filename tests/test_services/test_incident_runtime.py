import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.models.api import IncidentCreateRequest
from src.services.incident_runtime import ConfiguredIncidentInputValidator, _prune_expired_artifacts


@pytest.mark.asyncio
async def test_incident_input_validator_does_not_limit_video_size(tmp_path: Path) -> None:
    video = tmp_path / "camera.mp4"
    with video.open("wb") as output:
        output.truncate(250_000_001)
    settings = Settings(
        incident_input_roots=str(tmp_path),
        incident_upload_dir=str(tmp_path),
    )
    media = SimpleNamespace(probe_video=lambda _: _video_metadata())
    validator = ConfiguredIncidentInputValidator(settings=settings, media=media)

    await validator.validate(
        IncidentCreateRequest(
            incident_id="INC-LARGE-VIDEO",
            video_uri=str(video),
            analysis_prompt="Phân tích video.",
        )
    )


async def _video_metadata() -> SimpleNamespace:
    return SimpleNamespace(duration_s=10)


@pytest.mark.asyncio
async def test_artifact_retention_prunes_only_expired_unreferenced_incidents(tmp_path: Path) -> None:
    expired = tmp_path / "INC-EXPIRED"
    retained = tmp_path / "INC-RETAINED"
    expired.mkdir()
    retained.mkdir()
    old = (datetime.now(UTC) - timedelta(hours=48)).timestamp()
    os.utime(expired, (old, old))
    os.utime(retained, (old, old))

    await _prune_expired_artifacts(
        tmp_path,
        retention_hours=24,
        retained_incident_ids={"INC-RETAINED"},
    )

    assert not expired.exists()
    assert retained.exists()
