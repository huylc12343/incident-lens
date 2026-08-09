from pathlib import Path

import pytest

from src.models.api import StoredReport
from src.models.incidents import (
    DraftReport,
    IncidentWindow,
    ReportAlignmentSection,
    ReportEvidenceAndWarnings,
    ReportGeneralInformation,
    ReportLogSection,
    ReportTimelineSection,
    ReportVideoObservationsSection,
)
from src.services.report_repository import ReportRepositoryError, SQLiteReportRepository


def _stored_report() -> StoredReport:
    return StoredReport(
        incident_id="INC-STORED",
        status="approved",
        final_report=DraftReport(
            general_information=ReportGeneralInformation(
                incident_id="INC-STORED", video_uri="video.mp4", has_log=False
            ),
            incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
            summary="Summary",
            timeline=ReportTimelineSection(narrative="Timeline"),
            video_observations=ReportVideoObservationsSection(narrative="Video findings"),
            log_findings=ReportLogSection(narrative="Log findings"),
            alignment=ReportAlignmentSection(narrative="Aligned"),
            hypothesized_causes="Possible cause",
            evidence_and_warnings=ReportEvidenceAndWarnings(),
        ),
        evidence_ids=["frame-1"],
        reviewer="reviewer@example.com",
        decision="approve",
    )


def test_sqlite_repository_persists_across_instances(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    first = SQLiteReportRepository(str(database))
    stored = first.store(_stored_report())

    loaded = SQLiteReportRepository(str(database)).get("INC-STORED")

    assert loaded == stored
    assert loaded is not None
    assert loaded.stored_at is not None


def test_sqlite_repository_lists_reports_newest_first(tmp_path: Path) -> None:
    database = tmp_path / "reports.sqlite3"
    repository = SQLiteReportRepository(str(database))
    repository.store(_stored_report())

    reports = repository.list_reports()

    assert [report.incident_id for report in reports] == ["INC-STORED"]


def test_sqlite_repository_rejects_duplicate_terminal_outcome(tmp_path: Path) -> None:
    repository = SQLiteReportRepository(str(tmp_path / "reports.sqlite3"))
    repository.store(_stored_report())

    with pytest.raises(ReportRepositoryError) as exc_info:
        repository.store(_stored_report())

    assert exc_info.value.code == "REPORT_ALREADY_STORED"
