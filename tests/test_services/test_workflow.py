import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.api import IncidentCreateRequest, ReviewDecision
from src.models.incidents import (
    AnalysisMode,
    Claim,
    DraftReport,
    IncidentWindow,
    ReportAlignmentSection,
    ReportEvidenceAndWarnings,
    ReportGeneralInformation,
    ReportLogSection,
    ReportNarrative,
    ReportTimelineSection,
    ReportVideoObservationsSection,
    VideoMemory,
)
from src.services.report_repository import InMemoryReportRepository, ReportRepositoryError
from src.services.workflow import WorkflowError, WorkflowService


def _narrative() -> ReportNarrative:
    return ReportNarrative(
        summary="Summary",
        timeline="Timeline",
        video_observations="Video",
        log_findings="No log data",
        alignment="Unverified",
        hypothesized_causes="A hypothesis only",
    )


def _report(incident_id: str) -> DraftReport:
    narrative = _narrative()
    return DraftReport(
        general_information=ReportGeneralInformation(
            incident_id=incident_id,
            video_uri="video.mp4",
            has_log=False,
        ),
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        summary=narrative.summary,
        timeline=ReportTimelineSection(narrative=narrative.timeline),
        video_observations=ReportVideoObservationsSection(narrative=narrative.video_observations),
        log_findings=ReportLogSection(narrative=narrative.log_findings),
        alignment=ReportAlignmentSection(narrative=narrative.alignment),
        hypothesized_causes=narrative.hypothesized_causes,
        evidence_and_warnings=ReportEvidenceAndWarnings(),
    )


def _review_state(incident_id: str) -> dict[str, object]:
    memory = VideoMemory(
        global_scene="Road scene",
        video_summary="The vehicle approached a hazard and stopped after the incident.",
        incident_window=IncidentWindow(t_start=1, t0=2, t_end=3),
        claims=[Claim(claim_id="claim-1", text="Vehicle brakes")],
        analysis_mode=AnalysisMode.SINGLE_REQUEST,
    )
    return {
        "incident_id": incident_id,
        "status": "awaiting_review",
        "video_memory": memory,
        "claims": memory.claims,
        "report_narrative": _narrative(),
        "draft_report": _report(incident_id),
        "artifact_uris": {"incident_clip": "storage://clip.mp4"},
        "auto_reanalysis_count": 0,
        "manual_reanalysis_count": 0,
    }


@pytest.mark.asyncio
async def test_workflow_create_review_and_store_terminal_report() -> None:
    runner = SimpleNamespace(start=AsyncMock(), resume=AsyncMock())
    runner.start.side_effect = lambda state: _review_state(state["incident_id"])
    approved = {**_review_state("INC-API"), "status": "approved"}
    runner.resume.return_value = approved
    repository = InMemoryReportRepository()
    service = WorkflowService(runner=runner, repository=repository)

    pending = await service.create(
        IncidentCreateRequest(
            incident_id="INC-API",
            video_uri="data_mock/front_camera.mp4",
            analysis_prompt="Analyze the incident",
        )
    )
    terminal = await service.review(
        "INC-API",
        ReviewDecision(action="approve", reviewer="reviewer@example.com"),
    )

    assert pending.status == "awaiting_review"
    assert pending.video_summary == "The vehicle approached a hazard and stopped after the incident."
    assert pending.has_log is False
    assert terminal.status == "approved"
    assert terminal.final_report == _report("INC-API")
    assert terminal.stored_at is not None
    assert repository.get("INC-API") is not None


@pytest.mark.asyncio
async def test_workflow_rejects_duplicate_create_and_invalid_transition() -> None:
    runner = SimpleNamespace(start=AsyncMock(return_value=_review_state("INC-DUP")), resume=AsyncMock())
    service = WorkflowService(runner=runner, repository=InMemoryReportRepository())
    request = IncidentCreateRequest(
        incident_id="INC-DUP",
        video_uri="data_mock/front_camera.mp4",
        analysis_prompt="Analyze",
    )
    await service.create(request)

    with pytest.raises(WorkflowError) as duplicate:
        await service.create(request)
    assert duplicate.value.code == "INCIDENT_ALREADY_EXISTS"

    runner.resume.return_value = {**_review_state("INC-DUP"), "status": "approved"}
    await service.review("INC-DUP", ReviewDecision(action="approve", reviewer="reviewer"))
    with pytest.raises(WorkflowError) as invalid:
        await service.review("INC-DUP", ReviewDecision(action="approve", reviewer="reviewer"))
    assert invalid.value.code == "INVALID_REVIEW_TRANSITION"


@pytest.mark.asyncio
async def test_manual_reanalysis_rejects_unknown_target_before_resume() -> None:
    runner = SimpleNamespace(start=AsyncMock(return_value=_review_state("INC-MANUAL")), resume=AsyncMock())
    service = WorkflowService(runner=runner, repository=InMemoryReportRepository())
    await service.create(
        IncidentCreateRequest(
            incident_id="INC-MANUAL",
            video_uri="data_mock/front_camera.mp4",
            analysis_prompt="Analyze",
        )
    )

    with pytest.raises(WorkflowError) as exc_info:
        await service.review(
            "INC-MANUAL",
            ReviewDecision(
                action="reanalyze",
                reviewer="reviewer",
                feedback="Check again",
                target_claim_ids=["missing"],
            ),
        )

    assert exc_info.value.code == "REANALYSIS_TARGET_INVALID"
    runner.resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_reanalysis_can_return_to_review() -> None:
    initial = _review_state("INC-AGAIN")
    rerun = {**initial, "manual_reanalysis_count": 1}
    runner = SimpleNamespace(start=AsyncMock(return_value=initial), resume=AsyncMock(return_value=rerun))
    service = WorkflowService(runner=runner, repository=InMemoryReportRepository())
    await service.create(
        IncidentCreateRequest(
            incident_id="INC-AGAIN",
            video_uri="video.mp4",
            log_uri="vehicle.csv",
            analysis_prompt="Analyze",
        )
    )

    snapshot = await service.review(
        "INC-AGAIN",
        ReviewDecision(
            action="reanalyze",
            reviewer="reviewer",
            feedback="Inspect braking again",
            target_claim_ids=["claim-1"],
        ),
    )

    assert snapshot.status == "awaiting_review"
    assert snapshot.has_log is True
    assert snapshot.manual_reanalysis_count == 1
    assert snapshot.review_audit[0].feedback == "Inspect braking again"


@pytest.mark.asyncio
async def test_not_incident_stores_terminal_outcome() -> None:
    decision = ReviewDecision(action="not_incident", reviewer="reviewer", reason="No safety-relevant event")
    incident_id = "INC-NOT-INCIDENT"
    initial = _review_state(incident_id)
    terminal = {**initial, "status": "not_incident"}
    runner = SimpleNamespace(start=AsyncMock(return_value=initial), resume=AsyncMock(return_value=terminal))
    repository = InMemoryReportRepository()
    service = WorkflowService(runner=runner, repository=repository)
    await service.create(
        IncidentCreateRequest(incident_id=incident_id, video_uri="video.mp4", analysis_prompt="Analyze")
    )

    snapshot = await service.review(incident_id, decision)

    assert snapshot.status == "not_incident"
    stored = repository.get(incident_id)
    assert stored is not None
    assert stored.decision == decision.action
    assert stored.reason == decision.reason


@pytest.mark.asyncio
async def test_edit_returns_to_review_without_storing() -> None:
    initial = _review_state("INC-EDIT")
    edited_report = _report("INC-EDIT").model_copy(update={"summary": "Reviewed summary", "review_status": "edited"})
    runner = SimpleNamespace(
        start=AsyncMock(return_value=initial),
        resume=AsyncMock(return_value={**initial, "draft_report": edited_report}),
    )
    repository = InMemoryReportRepository()
    service = WorkflowService(runner=runner, repository=repository)
    await service.create(
        IncidentCreateRequest(incident_id="INC-EDIT", video_uri="video.mp4", analysis_prompt="Analyze")
    )

    snapshot = await service.review(
        "INC-EDIT",
        ReviewDecision(action="edit", reviewer="reviewer", edits={"summary": "Reviewed summary"}),
    )

    assert snapshot.status == "awaiting_review"
    assert snapshot.draft_report == edited_report
    assert repository.get("INC-EDIT") is None


@pytest.mark.asyncio
async def test_competing_review_decisions_store_exactly_once() -> None:
    initial = _review_state("INC-RACE")
    terminal = {**initial, "status": "approved"}
    runner = SimpleNamespace(start=AsyncMock(return_value=initial), resume=AsyncMock(return_value=terminal))
    repository = InMemoryReportRepository()
    service = WorkflowService(runner=runner, repository=repository)
    await service.create(
        IncidentCreateRequest(incident_id="INC-RACE", video_uri="video.mp4", analysis_prompt="Analyze")
    )
    decision = ReviewDecision(action="approve", reviewer="reviewer")

    results = await asyncio.gather(
        service.review("INC-RACE", decision),
        service.review("INC-RACE", decision),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    errors = [result for result in results if isinstance(result, WorkflowError)]
    assert len(errors) == 1
    assert errors[0].code == "INVALID_REVIEW_TRANSITION"
    assert runner.resume.await_count == 1
    assert repository.get("INC-RACE") is not None


@pytest.mark.asyncio
async def test_terminal_storage_failure_keeps_incident_reviewable() -> None:
    initial = _review_state("INC-STORAGE")
    terminal = {**initial, "status": "approved"}
    runner = SimpleNamespace(start=AsyncMock(return_value=initial), resume=AsyncMock(return_value=terminal))
    stored_reports = []

    def store(report):
        if not stored_reports:
            stored_reports.append(report)
            raise ReportRepositoryError("REPORT_STORAGE_FAILED", "database unavailable")
        return InMemoryReportRepository().store(report)

    repository = SimpleNamespace(store=store, get=lambda incident_id: None)
    service = WorkflowService(runner=runner, repository=repository)
    await service.create(
        IncidentCreateRequest(incident_id="INC-STORAGE", video_uri="video.mp4", analysis_prompt="Analyze")
    )
    decision = ReviewDecision(action="approve", reviewer="reviewer")

    with pytest.raises(WorkflowError) as first_attempt:
        await service.review("INC-STORAGE", decision)
    recovered = await service.get("INC-STORAGE")
    second_attempt = await service.review("INC-STORAGE", decision)

    assert first_attempt.value.code == "REPORT_STORAGE_FAILED"
    assert recovered.status == "awaiting_review"
    assert second_attempt.status == "approved"


@pytest.mark.asyncio
async def test_failed_snapshot_does_not_expose_provider_error_text() -> None:
    runner = SimpleNamespace(
        start=AsyncMock(
            return_value={
                "incident_id": "INC-FAILED",
                "status": "failed",
                "error_code": "OPENAI_VIDEO_ANALYSIS_FAILED",
                "error_message": "request failed with api_key=sk-secret-value",
            }
        ),
        resume=AsyncMock(),
    )
    service = WorkflowService(runner=runner, repository=InMemoryReportRepository())

    snapshot = await service.create(
        IncidentCreateRequest(incident_id="INC-FAILED", video_uri="video.mp4", analysis_prompt="Analyze")
    )

    assert snapshot.status == "failed"
    assert "sk-secret-value" not in (snapshot.error_message or "")


@pytest.mark.asyncio
async def test_failed_snapshot_explains_safe_openai_authentication_error() -> None:
    runner = SimpleNamespace(
        start=AsyncMock(
            return_value={
                "incident_id": "INC-AUTH-FAILED",
                "status": "failed",
                "error_code": "OPENAI_AUTHENTICATION_FAILED",
                "error_message": "raw provider detail",
            }
        ),
        resume=AsyncMock(),
    )
    service = WorkflowService(runner=runner, repository=InMemoryReportRepository())

    snapshot = await service.create(
        IncidentCreateRequest(incident_id="INC-AUTH-FAILED", video_uri="video.mp4", analysis_prompt="Analyze")
    )

    assert snapshot.error_message is not None
    assert "OPENAI_API_KEY" in snapshot.error_message
    assert "raw provider detail" not in snapshot.error_message


@pytest.mark.asyncio
async def test_invalid_runner_output_does_not_reserve_incident_id() -> None:
    runner = SimpleNamespace(
        start=AsyncMock(
            side_effect=[
                {"incident_id": "INC-INVALID", "status": "unknown"},
                _review_state("INC-INVALID"),
            ]
        ),
        resume=AsyncMock(),
    )
    service = WorkflowService(runner=runner, repository=InMemoryReportRepository())
    request = IncidentCreateRequest(
        incident_id="INC-INVALID",
        video_uri="video.mp4",
        analysis_prompt="Analyze",
    )

    with pytest.raises(WorkflowError) as exc_info:
        await service.create(request)
    recovered = await service.create(request)

    assert exc_info.value.code == "WORKFLOW_OUTPUT_INVALID"
    assert recovered.status == "awaiting_review"
