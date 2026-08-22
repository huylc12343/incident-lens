import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import src.main as main_module
from src.config import Settings
from src.models.api import IncidentCreateRequest, ReviewDecision
from src.models.incidents import (
    AccidentType,
    AnalysisMode,
    Claim,
    ClaimVerification,
    IncidentWindow,
    ReportModelOutput,
    VerificationResult,
    VerificationStatus,
    VideoMemory,
    VideoMemoryPatch,
)
from src.services.incident_runtime import ProviderClients, incident_workflow_service
from src.services.report_repository import SQLiteReportRepository


def _client(*responses: object) -> SimpleNamespace:
    return SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(side_effect=responses)))


def _qwen_client(*outputs: object) -> SimpleNamespace:
    responses = []
    for output in outputs:
        payload = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        responses.append(
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=responses))))


def _narrative(label: str = "Initial", accident_type: AccidentType = AccidentType.OTHER_UNKNOWN) -> ReportModelOutput:
    return ReportModelOutput(
        type_of_accident=accident_type,
        incident_window=IncidentWindow(t_start=6, t0=7, t_end=9),
        representative_timestamp_s=7,
        timeline=f"{label} timeline",
        video_observations=f"{label} observations",
        hypothesized_causes=f"{label} hypothesis",
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        incident_input_roots=str(Path("data_mock").resolve()),
        artifact_dir=str(tmp_path / "artifacts"),
        incident_database_path=str(tmp_path / "reports.sqlite3"),
        incident_checkpoint_path=str(tmp_path / "checkpoints.sqlite3"),
        vlm_reanalysis_frame_fps=1,
        vlm_reanalysis_max_frames=10,
        # Human-review orchestration is covered here; CV redaction has separate coverage.
        video_redaction_enabled=False,
    )


def _video_memory(*, with_claim: bool = True) -> VideoMemory:
    claims = [Claim(claim_id="claim-1", text="Vehicle brakes", timestamp_s=7.0)] if with_claim else []
    return VideoMemory(
        global_scene="Road scene",
        incident_window=IncidentWindow(t_start=6, t0=7, t_end=9),
        claims=claims,
        analysis_mode=AnalysisMode.NATIVE_VIDEO,
    )


@pytest.mark.asyncio
async def test_real_graph_edit_manual_reanalysis_restart_and_approve(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    vlm_client = _qwen_client(_video_memory())
    report_client = _client(
        SimpleNamespace(output_parsed=_narrative()),
        SimpleNamespace(
            output_parsed=VideoMemoryPatch(
                target_claim_ids=["claim-1"],
                claims=[Claim(claim_id="claim-1", text="Vehicle brakes later", timestamp_s=7.2)],
                base_revision=1,
            )
        ),
        SimpleNamespace(output_parsed=_narrative("Reanalyzed")),
    )
    clients = ProviderClients(
        qwen=vlm_client,
        openai_verification=_client(),
        openai_report=report_client,
    )

    async with incident_workflow_service(settings, clients=clients) as service:
        pending = await service.create(
            IncidentCreateRequest(
                incident_id="INC-PERSIST",
                video_uri="data_mock/data1/front_camera.mp4",
                analysis_prompt="Analyze the incident",
            )
        )
        edited = await service.review(
            "INC-PERSIST",
            ReviewDecision(action="edit", reviewer="tech", edits={"summary": "Human-edited summary"}),
        )
        reanalyzed = await service.review(
            "INC-PERSIST",
            ReviewDecision(
                action="reanalyze",
                reviewer="tech",
                feedback="Inspect braking again",
                target_claim_ids=["claim-1"],
            ),
        )

        assert pending.status == "awaiting_review"
        assert edited.status == "awaiting_review"
        assert edited.draft_report is not None
        assert edited.draft_report.summary == "Human-edited summary"
        assert reanalyzed.status == "awaiting_review"
        assert reanalyzed.manual_reanalysis_count == 1
        assert vlm_client.chat.completions.create.await_count == 1
        assert report_client.responses.parse.await_count == 3

    restart_clients = ProviderClients(
        qwen=_qwen_client(),
        openai_verification=_client(),
        openai_report=_client(),
    )
    async with incident_workflow_service(settings, clients=restart_clients) as restarted:
        recovered = await restarted.get("INC-PERSIST")
        terminal = await restarted.review(
            "INC-PERSIST",
            ReviewDecision(action="approve", reviewer="supervisor"),
        )

    assert recovered.status == "awaiting_review"
    assert [entry.action for entry in recovered.review_audit] == ["edit", "reanalyze"]
    assert terminal.status == "approved"
    assert terminal.final_report is not None
    assert terminal.final_report.review_status == "approved"
    stored = SQLiteReportRepository(settings.incident_database_path).get("INC-PERSIST")
    assert stored is not None
    assert [entry.action for entry in stored.review_audit] == ["edit", "reanalyze", "approve"]


@pytest.mark.asyncio
async def test_real_graph_log_conflict_reanalyzes_once_and_reports_warning(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    vlm_client = _qwen_client(
        _video_memory(),
        VideoMemoryPatch(
            target_claim_ids=["claim-1"],
            claims=[Claim(claim_id="claim-1", text="Vehicle brakes", timestamp_s=7.1)],
            base_revision=1,
        ),
    )
    contradicted = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Log does not support the video claim",
                evidence_ids=["log-row:7"],
            )
        ]
    )
    clients = ProviderClients(
        qwen=vlm_client,
        openai_verification=_client(
            SimpleNamespace(output_parsed=contradicted),
            SimpleNamespace(output_parsed=contradicted),
        ),
        openai_report=_client(SimpleNamespace(output_parsed=_narrative())),
    )

    async with incident_workflow_service(settings, clients=clients) as service:
        pending = await service.create(
            IncidentCreateRequest(
                incident_id="INC-CONFLICT",
                video_uri="data_mock/data1/front_camera.mp4",
                log_uri="data_mock/data1/vehicle_state.csv",
                analysis_prompt="Analyze the incident",
            )
        )

    assert pending.status == "awaiting_review"
    assert pending.auto_reanalysis_count == 1
    assert pending.conflict_claim_ids == ["claim-1"]
    assert any("claim-1" in warning for warning in pending.warnings)
    assert vlm_client.chat.completions.create.await_count == 2
    assert len([key for key in pending.artifact_uris if key.startswith("chart_")]) == 4


@pytest.mark.asyncio
async def test_fastapi_lifespan_bootstraps_configured_workflow(monkeypatch, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    clients = ProviderClients(
        qwen=_qwen_client(_video_memory(with_claim=False)),
        openai_verification=_client(),
        openai_report=_client(SimpleNamespace(output_parsed=_narrative(accident_type=AccidentType.NO_INCIDENT))),
    )

    @asynccontextmanager
    async def configured_runtime(runtime_settings: Settings):
        async with incident_workflow_service(runtime_settings, clients=clients) as service:
            yield service

    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "incident_workflow_service", configured_runtime)
    async with main_module.app.router.lifespan_context(main_module.app):
        async with AsyncClient(
            transport=ASGITransport(app=main_module.app),
            base_url="http://test",
        ) as client:
            health = await client.get("/health")
            created = await client.post(
                "/api/v1/incidents",
                json={
                    "incident_id": "INC-BOOTSTRAP",
                    "video_uri": "data_mock/data1/front_camera.mp4",
                    "analysis_prompt": "Analyze",
                },
            )
            closed = await client.post(
                "/api/v1/incidents/INC-BOOTSTRAP/review",
                json={
                    "action": "not_incident",
                    "reviewer": "api-reviewer",
                    "reason": "No safety-relevant event",
                },
            )

    assert health.status_code == 200
    assert created.status_code == 202
    assert created.json()["status"] == "awaiting_review"
    assert created.json()["draft_report"]["type_of_accident"] == "no_incident"
    activities = created.json()["model_activities"]
    assert [(item["step"], item["status"]) for item in activities] == [
        ("vlm", "completed"),
        ("report", "completed"),
    ]
    assert all(item["model"] for item in activities)
    assert closed.status_code == 200
    assert closed.json()["status"] == "not_incident"
