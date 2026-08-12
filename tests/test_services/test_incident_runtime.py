import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.services.incident_runtime import _prune_expired_artifacts


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
