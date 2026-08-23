"""Application service for starting, resuming, and safely exposing incidents."""

from __future__ import annotations

import asyncio
import re
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from src.agents.incident_state import IncidentState
from src.models.api import (
    IncidentCreateRequest,
    IncidentSnapshot,
    ReviewAuditEntry,
    ReviewDecision,
    StoredReport,
)
from src.models.incidents import VerificationStatus
from src.services.model_observability import ModelActivityRegistry
from src.services.report_repository import ReportRepository, ReportRepositoryError


class WorkflowError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IncidentGraphRunner(Protocol):
    async def start(self, state: IncidentState) -> IncidentState: ...

    async def resume(self, incident_id: str, decision: ReviewDecision) -> IncidentState: ...

    async def get(self, incident_id: str) -> IncidentState | None: ...

    async def list_incident_ids(self) -> list[str]: ...

    async def delete(self, incident_id: str) -> None: ...


class IncidentInputValidator(Protocol):
    async def validate(self, request: IncidentCreateRequest) -> None: ...


class WorkflowService:
    def __init__(
        self,
        *,
        runner: IncidentGraphRunner,
        repository: ReportRepository,
        input_validator: IncidentInputValidator | None = None,
        observability: ModelActivityRegistry | None = None,
        artifact_dir: str | None = None,
        upload_dir: str | None = None,
        remote_resource_releaser: Callable[[list], Awaitable[None]] | None = None,
    ) -> None:
        self._runner = runner
        self._repository = repository
        self._input_validator = input_validator
        self._observability = observability
        self._artifact_root = Path(artifact_dir).resolve() if artifact_dir else None
        self._upload_root = Path(upload_dir).resolve() if upload_dir else None
        self._remote_resource_releaser = remote_resource_releaser
        self._states: dict[str, IncidentState] = {}
        self._review_locks: dict[str, asyncio.Lock] = {}
        self._audit: dict[str, list[ReviewAuditEntry]] = {}
        self._stored_at: dict[str, datetime] = {}
        self._pending_terminal: dict[str, tuple[IncidentState, ReviewDecision]] = {}
        self._workflow_tasks: dict[str, asyncio.Task[None]] = {}
        self._registry_lock = asyncio.Lock()

    async def create(self, request: IncidentCreateRequest) -> IncidentSnapshot:
        if self._input_validator is not None:
            await self._input_validator.validate(request)
        incident_id = request.incident_id.strip()
        initial: IncidentState = {
            "incident_id": incident_id,
            "video_uri": request.video_uri,
            "log_uri": request.log_uri,
            "analysis_prompt": request.analysis_prompt,
            "metadata": request.metadata,
            "status": "queued",
            "auto_reanalysis_count": 0,
            "manual_reanalysis_count": 0,
            "artifact_uris": {},
            "warnings": [],
            "review_audit": [],
            "model_activities": [],
        }
        async with self._registry_lock:
            checkpoint_state = await self._checkpoint_state(incident_id)
            if (
                incident_id in self._states
                or checkpoint_state is not None
                or await _repository_call(self._repository, "aget", "get", incident_id) is not None
            ):
                raise WorkflowError("INCIDENT_ALREADY_EXISTS", "incident ID already exists")
            self._states[incident_id] = initial
            self._review_locks[incident_id] = asyncio.Lock()
            self._audit[incident_id] = []
        # The HTTP request only reserves an incident and schedules the expensive
        # graph.  Clients receive this queued snapshot and follow state changes
        # through GET /incidents/{incident_id}; this is the same lifecycle used
        # by the Streamlit client.
        self._workflow_tasks[incident_id] = asyncio.create_task(
            self._run_enqueued(initial), name=f"incident-workflow-{incident_id}"
        )
        return self._snapshot(initial)

    async def _run_enqueued(self, initial: IncidentState) -> None:
        incident_id = initial["incident_id"]
        running = {**initial, "status": "running"}
        self._states[incident_id] = running
        try:
            result = await self._runner.start(running)
            state = _without_legacy_claim_projection({**running, **result})
            self._snapshot(state)
        except Exception as exc:
            code = exc.code if isinstance(exc, WorkflowError) else "WORKFLOW_EXECUTION_FAILED"
            state = {
                **running,
                "status": "failed",
                "error_code": code,
                "error_message": "incident workflow could not complete",
            }
        self._states[incident_id] = state
        self._workflow_tasks.pop(incident_id, None)

    async def get(self, incident_id: str) -> IncidentSnapshot:
        state = self._states.get(incident_id)
        if state is None:
            state = await self._checkpoint_state(incident_id)
            if state is not None and state.get("status") not in {"approved", "not_incident"}:
                await self._register_recovered_state(incident_id, state)
        if state is not None:
            return self._snapshot(state)
        stored = await _repository_call(self._repository, "aget", "get", incident_id)
        if stored is None:
            raise WorkflowError("INCIDENT_NOT_FOUND", "incident does not exist")
        return _stored_snapshot(stored)

    async def list_reports(self) -> list[StoredReport]:
        return await _repository_call(self._repository, "alist_reports", "list_reports")

    async def list_incident_ids(self) -> list[str]:
        checkpoint_ids = await self._runner.list_incident_ids()
        reports = await _repository_call(self._repository, "alist_reports", "list_reports")
        report_ids = [report.incident_id for report in reports]
        return list(dict.fromkeys([*checkpoint_ids, *report_ids]))

    async def ready(self) -> None:
        await self._runner.list_incident_ids()
        await _repository_call(self._repository, "alist_reports", "list_reports")

    async def delete(self, incident_id: str) -> None:
        async with self._registry_lock:
            lock = self._review_locks.setdefault(incident_id, asyncio.Lock())
        async with lock:
            state = self._states.get(incident_id) or await self._checkpoint_state(incident_id)
            stored = await _repository_call(self._repository, "aget", "get", incident_id)
            if state is None and stored is None:
                raise WorkflowError("INCIDENT_NOT_FOUND", "incident does not exist")
            if state is not None and state.get("status") in {"queued", "running"}:
                raise WorkflowError("INCIDENT_DELETE_ACTIVE", "running incident cannot be deleted")
            await self._cleanup_incident_resources(incident_id, state)
            await self._runner.delete(incident_id)
            await _repository_call(self._repository, "adelete", "delete", incident_id)
            async with self._registry_lock:
                self._states.pop(incident_id, None)
                self._review_locks.pop(incident_id, None)
                self._audit.pop(incident_id, None)
                self._stored_at.pop(incident_id, None)
                self._pending_terminal.pop(incident_id, None)
                self._workflow_tasks.pop(incident_id, None)
            if self._observability is not None:
                self._observability.delete(incident_id)

    async def _cleanup_incident_resources(self, incident_id: str, state: IncidentState | None) -> None:
        if state is not None and self._remote_resource_releaser is not None:
            handles = state.get("remote_media_handles", [])
            if handles:
                try:
                    await self._remote_resource_releaser(handles)
                except Exception:
                    pass
        targets: list[Path] = []
        if self._artifact_root is not None:
            safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", incident_id)
            targets.append(self._artifact_root / safe_id)
        if state is not None and self._upload_root is not None:
            for value in (state.get("video_uri"), state.get("log_uri")):
                if not value:
                    continue
                path = Path(value).resolve()
                if path.is_relative_to(self._upload_root):
                    targets.append(path)
        for target in targets:
            _delete_scoped_path(target)

    async def review(self, incident_id: str, decision: ReviewDecision) -> IncidentSnapshot:
        # Give a just-enqueued workflow a chance to publish its first state
        # before evaluating the review transition.  This keeps in-process API
        # callers deterministic without making the create endpoint synchronous.
        await asyncio.sleep(0)
        lock = self._review_locks.get(incident_id)
        if lock is None:
            recovered = await self._checkpoint_state(incident_id)
            if recovered is not None and recovered.get("status") == "awaiting_review":
                await self._register_recovered_state(incident_id, recovered)
                lock = self._review_locks[incident_id]
        if lock is None:
            if await _repository_call(self._repository, "aget", "get", incident_id) is not None:
                raise WorkflowError("INVALID_REVIEW_TRANSITION", "incident is already terminal")
            raise WorkflowError("INCIDENT_NOT_FOUND", "incident does not exist")
        async with lock:
            state = self._states.get(incident_id)
            if state is None:
                raise WorkflowError("INCIDENT_NOT_FOUND", "incident does not exist")
            pending = self._pending_terminal.get(incident_id)
            if pending is not None:
                pending_state, pending_decision = pending
                if decision != pending_decision:
                    raise WorkflowError("INVALID_REVIEW_TRANSITION", "a terminal decision is pending storage")
                stored = await self._store_terminal(pending_state, decision)
                self._commit_review(incident_id, pending_state, decision, stored.stored_at)
                self._pending_terminal.pop(incident_id, None)
                return self._snapshot(pending_state)
            if state.get("status") != "awaiting_review":
                raise WorkflowError("INVALID_REVIEW_TRANSITION", "incident is not awaiting review")
            if decision.action == "reanalyze":
                memory = state.get("video_memory")
                claim_ids = {claim.claim_id for claim in memory.claims} if memory is not None else set()
                invalid_targets = set(decision.target_claim_ids) - claim_ids
                if invalid_targets:
                    raise WorkflowError("REANALYSIS_TARGET_INVALID", "re-analysis target claim does not exist")
                if self._observability is not None:
                    provider_calls = 3 if state.get("log_uri") else 2
                    self._observability.grant_additional_requests(incident_id, provider_calls)
            try:
                result = await self._runner.resume(incident_id, decision)
            except Exception as exc:
                if isinstance(exc, WorkflowError):
                    raise
                raise WorkflowError("WORKFLOW_EXECUTION_FAILED", "incident workflow could not resume") from exc
            updated = _without_legacy_claim_projection({**state, **result})
            try:
                self._snapshot(updated)
            except Exception as exc:
                raise WorkflowError("WORKFLOW_OUTPUT_INVALID", "incident workflow returned invalid state") from exc
            if updated.get("status") in {"approved", "not_incident"}:
                try:
                    stored = await self._store_terminal(updated, decision)
                except WorkflowError:
                    self._pending_terminal[incident_id] = (updated, decision)
                    raise
                self._commit_review(incident_id, updated, decision, stored.stored_at)
            else:
                self._commit_review(incident_id, updated, decision)
            return self._snapshot(updated)

    def _commit_review(
        self,
        incident_id: str,
        state: IncidentState,
        decision: ReviewDecision,
        stored_at: datetime | None = None,
    ) -> None:
        self._states[incident_id] = state
        self._audit[incident_id].append(
            ReviewAuditEntry(
                action=decision.action,
                reviewer=decision.reviewer,
                reason=decision.reason,
                feedback=decision.feedback,
                target_claim_ids=decision.target_claim_ids,
            )
        )
        if stored_at is not None:
            self._stored_at[incident_id] = stored_at

    async def _register_recovered_state(self, incident_id: str, state: IncidentState) -> None:
        if self._observability is not None:
            self._observability.restore(incident_id, state.get("model_activities", []))
        async with self._registry_lock:
            self._states.setdefault(incident_id, state)
            self._review_locks.setdefault(incident_id, asyncio.Lock())
            self._audit.setdefault(incident_id, [])

    async def _checkpoint_state(self, incident_id: str) -> IncidentState | None:
        getter = getattr(self._runner, "get", None)
        state = await getter(incident_id) if getter is not None else None
        return _without_legacy_claim_projection(state) if state is not None else None

    async def _store_terminal(self, state: IncidentState, decision: ReviewDecision) -> StoredReport:
        status = state.get("status")
        evidence_ids = []
        memory = state.get("video_memory")
        if memory is not None:
            evidence_ids.extend(evidence.evidence_id for claim in memory.claims for evidence in claim.evidence)
        log_summary = state.get("log_evidence_summary")
        if log_summary is not None:
            evidence_ids.extend(log_summary.evidence_ids)
        verification = state.get("verification")
        if verification is not None:
            evidence_ids.extend(
                evidence_id for result in verification.results for evidence_id in result.evidence_ids
            )
        report = state.get("report_narrative")
        if report is not None:
            evidence_ids.extend(report.evidence_ids)
        try:
            report_to_store = StoredReport(
                    incident_id=state["incident_id"],
                    status=cast(str, status),
                    has_log=bool(state.get("log_uri")),
                    artifact_uris=state.get("artifact_uris", {}),
                    claims=memory.claims if memory is not None else [],
                    warnings=state.get("warnings", []),
                    review_audit=state.get("review_audit", []),
                    model_activities=state.get("model_activities", []),
                    final_report=state.get("draft_report") if status == "approved" else None,
                    evidence_ids=list(dict.fromkeys(evidence_ids)),
                    reviewer=decision.reviewer,
                    decision=cast(str, decision.action),
                    reason=decision.reason,
                )
            return await _repository_call(self._repository, "astore", "store", report_to_store)
        except (ReportRepositoryError, ValueError) as exc:
            raise WorkflowError(
                getattr(exc, "code", "REPORT_STORAGE_INVALID"),
                "terminal outcome could not be stored",
            ) from exc

    def _snapshot(self, state: IncidentState) -> IncidentSnapshot:
        incident_id = state["incident_id"]
        memory = state.get("video_memory")
        claims = memory.claims if memory is not None else []
        verification = state.get("verification")
        conflicts = [
            item.claim_id for item in (verification.results if verification else [])
            if item.status == VerificationStatus.CONTRADICTED
        ]
        status = state.get("status", "failed")
        report = state.get("draft_report")
        video_summary = ""
        if memory is not None:
            video_summary = memory.video_summary or memory.global_scene
        activities = state.get("model_activities", [])
        if self._observability is not None:
            live_activities = self._observability.list(incident_id)
            if live_activities:
                activities = live_activities
        return IncidentSnapshot(
            incident_id=incident_id,
            status=status,
            has_log=bool(state.get("log_uri")),
            video_summary=video_summary,
            artifact_uris=state.get("artifact_uris", {}),
            claims=claims,
            claim_log_summaries=state.get("claim_log_summaries", []),
            conflict_claim_ids=conflicts,
            auto_reanalysis_count=state.get("auto_reanalysis_count", 0),
            manual_reanalysis_count=state.get("manual_reanalysis_count", 0),
            draft_report=report if status == "awaiting_review" else None,
            final_report=report if status == "approved" else None,
            review_audit=state.get("review_audit") or self._audit.get(incident_id, []),
            model_activities=activities,
            warnings=state.get("warnings", []),
            error_code=state.get("error_code"),
            error_message=_safe_processing_error(state.get("error_code")) if state.get("error_message") else None,
            stored_at=self._stored_at.get(incident_id),
        )


def _without_legacy_claim_projection(state: dict[str, object]) -> IncidentState:
    return cast(IncidentState, {key: value for key, value in state.items() if key != "claims"})


def _stored_snapshot(stored: StoredReport) -> IncidentSnapshot:
    return IncidentSnapshot(
        incident_id=stored.incident_id,
        status=stored.status,
        has_log=stored.has_log,
        video_summary=stored.final_report.summary if stored.final_report is not None else "",
        artifact_uris=stored.artifact_uris,
        claims=stored.claims,
        claim_log_summaries=(stored.final_report.log_findings.claim_summaries if stored.final_report else []),
        conflict_claim_ids=[],
        warnings=stored.warnings,
        model_activities=stored.model_activities,
        final_report=stored.final_report,
        review_audit=stored.review_audit
        or [ReviewAuditEntry(action=stored.decision, reviewer=stored.reviewer, reason=stored.reason)],
        stored_at=stored.stored_at,
    )


def _safe_processing_error(code: str | None) -> str:
    return {
        "OPENAI_AUTHENTICATION_FAILED": "OpenAI từ chối API key. Kiểm tra OPENAI_API_KEY rồi khởi động lại FastAPI.",
        "OPENAI_PERMISSION_DENIED": "API key không có quyền dùng model OpenAI đã cấu hình.",
        "OPENAI_RATE_LIMITED": (
            "OpenAI hết quota hoặc đang rate-limit. Kiểm tra Billing/Usage rồi thử lại với incident ID mới."
        ),
        "OPENAI_VERIFICATION_TIMEOUT": "OpenAI verification quá thời gian chờ. Thử lại hoặc tăng VERIFICATION_TIMEOUT_S.",
        "OPENAI_CONNECTION_FAILED": "Backend không kết nối được tới OpenAI. Kiểm tra mạng/proxy của máy chạy FastAPI.",
        "OPENAI_VERIFICATION_REQUEST_INVALID": (
            "OpenAI từ chối model hoặc structured request verification. Kiểm tra VERIFICATION_MODEL_NAME."
        ),
        "DASHSCOPE_AUTHENTICATION_FAILED": (
            "DashScope từ chối API key. Kiểm tra DASHSCOPE_API_KEY rồi khởi động lại FastAPI."
        ),
        "QWEN_QUOTA_EXHAUSTED": (
            "DashScope đã hết free quota. Bổ sung thông tin thanh toán hoặc tắt chế độ "
            "'use free tier only' trong DashScope console, rồi thử lại với incident ID mới."
        ),
        "QWEN_PERMISSION_DENIED": "DashScope API key không có quyền dùng model Qwen đã cấu hình.",
        "QWEN_VIDEO_ANALYSIS_REQUEST_INVALID": (
            "DashScope từ chối model, video hoặc request phân tích. Kiểm tra QWEN_MODEL_NAME và cấu hình video."
        ),
        "VERIFICATION_STRUCTURED_OUTPUT_INVALID": "OpenAI trả kết quả verification không đúng schema.",
        "VLM_STRUCTURED_OUTPUT_INVALID": (
            "VLM trả dữ liệu không đúng schema. Request không được tự động gọi lại khi retry được cấu hình bằng 0."
        ),
        "VLM_TIMESTAMP_OUTSIDE_INCIDENT_WINDOW": (
            "VLM trả timeline, claim hoặc evidence nằm ngoài incident window; backend đã từ chối kết quả này."
        ),
        "VLM_NATIVE_EVIDENCE_MAPPING_FAILED": (
            "Không tìm thấy sampled frame đủ gần timestamp của claim/evidence native-video."
        ),
        "VLM_EVIDENCE_REFERENCE_INVALID": (
            "VLM trả evidence_id không tồn tại trong các frame đã phân tích. Hãy chạy lại bằng incident ID mới."
        ),
    }.get(code, "incident processing failed")


def _delete_scoped_path(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()


async def _repository_call(repository: ReportRepository, async_name: str, sync_name: str, *args):
    async_method = getattr(repository, async_name, None)
    if async_method is not None:
        return await async_method(*args)
    return getattr(repository, sync_name)(*args)
