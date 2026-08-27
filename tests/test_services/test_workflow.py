import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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
from src.services.model_observability import ModelActivityRegistry
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
async def test_workflow_uses_video_memory_claims_over_legacy_top_level_claims() -> None:
    initial = _review_state("INC-CANONICAL-CLAIMS")
    initial["claims"] = [Claim(claim_id="stale-claim", text="Stale claim")]
    terminal = {**initial, "status": "approved"}
    runner = SimpleNamespace(start=AsyncMock(return_value=initial), resume=AsyncMock(return_value=terminal))
    repository = InMemoryReportRepository()
    service = WorkflowService(runner=runner, repository=repository)

    pending = await service.create(
        IncidentCreateRequest(
            incident_id="INC-CANONICAL-CLAIMS",
            video_uri="data_mock/front_camera.mp4",
            analysis_prompt="Analyze the incident",
        )
    )
    await service.review("INC-CANONICAL-CLAIMS", ReviewDecision(action="approve", reviewer="reviewer"))

    assert [claim.claim_id for claim in pending.claims] == ["claim-1"]
    assert "claims" not in service._states["INC-CANONICAL-CLAIMS"]
    stored = repository.get("INC-CANONICAL-CLAIMS")
    assert stored is not None
    assert [claim.claim_id for claim in stored.claims] == ["claim-1"]


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
async def test_manual_reanalysis_grants_budget_for_reanalyze_verify_and_report() -> None:
    initial = _review_state("INC-REANALYZE-BUDGET")
    initial["log_uri"] = "vehicle.csv"
    runner = SimpleNamespace(start=AsyncMock(return_value=initial), resume=AsyncMock(return_value=initial))
    observability = Mock(wraps=ModelActivityRegistry())
    service = WorkflowService(
        runner=runner,
        repository=InMemoryReportRepository(),
        observability=observability,
    )
    await service.create(
        IncidentCreateRequest(
            incident_id="INC-REANALYZE-BUDGET",
            video_uri="video.mp4",
            log_uri="vehicle.csv",
            analysis_prompt="Analyze",
        )
    )

    await service.review(
        "INC-REANALYZE-BUDGET",
        ReviewDecision(
            action="reanalyze",
            reviewer="reviewer",
            feedback="Inspect again",
            target_claim_ids=["claim-1"],
        ),
    )

    observability.grant_additional_requests.assert_called_once_with("INC-REANALYZE-BUDGET", 3)


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
                "error_code": "QWEN_VIDEO_ANALYSIS_FAILED",
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


@pytest.mark.asyncio
async def test_workflow_lists_and_deletes_one_incident_history() -> None:
    runner = SimpleNamespace(
        start=AsyncMock(return_value=_review_state("INC-HISTORY")),
        resume=AsyncMock(),
        get=AsyncMock(return_value=None),
        list_incident_ids=AsyncMock(return_value=["INC-HISTORY"]),
        delete=AsyncMock(return_value=None),
    )
    repository = InMemoryReportRepository()
    service = WorkflowService(runner=runner, repository=repository)
    await service.create(
        IncidentCreateRequest(incident_id="INC-HISTORY", video_uri="video.mp4", analysis_prompt="Analyze")
    )

    assert await service.list_incident_ids() == ["INC-HISTORY"]
    await service.delete("INC-HISTORY")

    runner.delete.assert_awaited_once_with("INC-HISTORY")
    with pytest.raises(WorkflowError) as exc_info:
        await service.get("INC-HISTORY")
    assert exc_info.value.code == "INCIDENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_workflow_deletes_running_incident_history() -> None:
    running_state = {**_review_state("INC-RUNNING"), "status": "running"}
    runner = SimpleNamespace(
        start=AsyncMock(return_value=running_state),
        resume=AsyncMock(),
        get=AsyncMock(return_value=None),
        list_incident_ids=AsyncMock(return_value=["INC-RUNNING"]),
        delete=AsyncMock(return_value=None),
    )
    service = WorkflowService(runner=runner, repository=InMemoryReportRepository())
    await service.create(
        IncidentCreateRequest(incident_id="INC-RUNNING", video_uri="video.mp4", analysis_prompt="Analyze")
    )

    await service.delete("INC-RUNNING")

    runner.delete.assert_awaited_once_with("INC-RUNNING")
    with pytest.raises(WorkflowError) as exc_info:
        await service.get("INC-RUNNING")
    assert exc_info.value.code == "INCIDENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_cancels_active_incident_analysis() -> None:
    started = asyncio.Event()

    async def start(_state):
        started.set()
        await asyncio.Event().wait()

    runner = SimpleNamespace(
        start=AsyncMock(side_effect=start),
        resume=AsyncMock(),
        get=AsyncMock(return_value=None),
        list_incident_ids=AsyncMock(return_value=["INC-ACTIVE"]),
        delete=AsyncMock(return_value=None),
    )
    service = WorkflowService(runner=runner, repository=InMemoryReportRepository())
    create_task = asyncio.create_task(
        service.create(IncidentCreateRequest(incident_id="INC-ACTIVE", video_uri="video.mp4", analysis_prompt="A"))
    )
    await started.wait()

    await service.delete("INC-ACTIVE")

    assert create_task.cancelled()
    runner.delete.assert_awaited_once_with("INC-ACTIVE")
    with pytest.raises(WorkflowError) as exc_info:
        await service.get("INC-ACTIVE")
    assert exc_info.value.code == "INCIDENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_detached_create_returns_running_and_survives_caller_completion() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def start(_state):
        started.set()
        await release.wait()
        completed.set()
        return _review_state("INC-DETACHED")

    runner = SimpleNamespace(
        start=AsyncMock(side_effect=start),
        resume=AsyncMock(),
        get=AsyncMock(return_value=None),
        list_incident_ids=AsyncMock(return_value=["INC-DETACHED"]),
        delete=AsyncMock(return_value=None),
    )
    service = WorkflowService(runner=runner, repository=InMemoryReportRepository())

    initial = await service.create_detached(
        IncidentCreateRequest(incident_id="INC-DETACHED", video_uri="video.mp4", analysis_prompt="Analyze")
    )

    assert started.is_set()
    assert initial.status == "running"
    release.set()
    await completed.wait()
    await asyncio.sleep(0)
    assert (await service.get("INC-DETACHED")).status == "awaiting_review"


@pytest.mark.asyncio
async def test_delete_removes_incident_artifacts_and_uploaded_inputs(tmp_path) -> None:
    artifact_dir = tmp_path / "artifacts"
    incident_dir = artifact_dir / "INC-CLEAN"
    incident_dir.mkdir(parents=True)
    (incident_dir / "clip.mp4").write_bytes(b"clip")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    uploaded_video = upload_dir / "video.mp4"
    uploaded_video.write_bytes(b"video")
    state = {**_review_state("INC-CLEAN"), "remote_media_handles": ["remote-handle"]}
    runner = SimpleNamespace(
        start=AsyncMock(return_value=state),
        resume=AsyncMock(),
        get=AsyncMock(return_value=None),
        list_incident_ids=AsyncMock(return_value=["INC-CLEAN"]),
        delete=AsyncMock(return_value=None),
    )
    releaser = AsyncMock()
    service = WorkflowService(
        runner=runner,
        repository=InMemoryReportRepository(),
        artifact_dir=str(artifact_dir),
        upload_dir=str(upload_dir),
        remote_resource_releaser=releaser,
    )
    await service.create(
        IncidentCreateRequest(incident_id="INC-CLEAN", video_uri=str(uploaded_video), analysis_prompt="Analyze")
    )

    await service.delete("INC-CLEAN")

    assert not incident_dir.exists()
    assert not uploaded_video.exists()
    releaser.assert_awaited_once_with(["remote-handle"])


@pytest.mark.asyncio
async def test_delete_waits_for_in_flight_review_transaction() -> None:
    review_started = asyncio.Event()
    release_review = asyncio.Event()

    async def resume(_incident_id, _decision):
        review_started.set()
        await release_review.wait()
        return {**_review_state("INC-RACE"), "status": "not_incident"}

    runner = SimpleNamespace(
        start=AsyncMock(return_value=_review_state("INC-RACE")),
        resume=AsyncMock(side_effect=resume),
        get=AsyncMock(return_value=None),
        list_incident_ids=AsyncMock(return_value=["INC-RACE"]),
        delete=AsyncMock(return_value=None),
    )
    repository = InMemoryReportRepository()
    service = WorkflowService(runner=runner, repository=repository)
    await service.create(IncidentCreateRequest(incident_id="INC-RACE", video_uri="video.mp4", analysis_prompt="A"))

    review_task = asyncio.create_task(
        service.review(
            "INC-RACE",
            ReviewDecision(action="not_incident", reviewer="reviewer", reason="Not an incident"),
        )
    )
    await review_started.wait()
    delete_task = asyncio.create_task(service.delete("INC-RACE"))
    await asyncio.sleep(0)
    assert not delete_task.done()

    release_review.set()
    await review_task
    await delete_task

    runner.delete.assert_awaited_once_with("INC-RACE")
    assert repository.get("INC-RACE") is None
