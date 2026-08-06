"""Application service for starting, resuming, and safely exposing incidents."""

from __future__ import annotations

import asyncio
from datetime import datetime
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
from src.services.report_repository import ReportRepository, ReportRepositoryError


class WorkflowError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IncidentGraphRunner(Protocol):
    async def start(self, state: IncidentState) -> IncidentState: ...

    async def resume(self, incident_id: str, decision: ReviewDecision) -> IncidentState: ...

    async def get(self, incident_id: str) -> IncidentState | None: ...


class IncidentInputValidator(Protocol):
    async def validate(self, request: IncidentCreateRequest) -> None: ...


class WorkflowService:
    def __init__(
        self,
        *,
        runner: IncidentGraphRunner,
        repository: ReportRepository,
        input_validator: IncidentInputValidator | None = None,
    ) -> None:
        self._runner = runner
        self._repository = repository
        self._input_validator = input_validator
        self._states: dict[str, IncidentState] = {}
        self._review_locks: dict[str, asyncio.Lock] = {}
        self._audit: dict[str, list[ReviewAuditEntry]] = {}
        self._stored_at: dict[str, datetime] = {}
        self._pending_terminal: dict[str, tuple[IncidentState, ReviewDecision]] = {}
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
            "status": "running",
            "auto_reanalysis_count": 0,
            "manual_reanalysis_count": 0,
            "artifact_uris": {},
            "warnings": [],
            "review_audit": [],
        }
        async with self._registry_lock:
            checkpoint_state = await self._checkpoint_state(incident_id)
            if (
                incident_id in self._states
                or checkpoint_state is not None
                or self._repository.get(incident_id) is not None
            ):
                raise WorkflowError("INCIDENT_ALREADY_EXISTS", "incident ID already exists")
            self._states[incident_id] = initial
            self._review_locks[incident_id] = asyncio.Lock()
            self._audit[incident_id] = []
        try:
            result = await self._runner.start(initial)
        except Exception as exc:
            async with self._registry_lock:
                self._states.pop(incident_id, None)
                self._review_locks.pop(incident_id, None)
                self._audit.pop(incident_id, None)
            if isinstance(exc, WorkflowError):
                raise
            raise WorkflowError("WORKFLOW_EXECUTION_FAILED", "incident workflow could not start") from exc
        state = cast(IncidentState, {**initial, **result})
        try:
            snapshot = self._snapshot(state)
        except Exception as exc:
            async with self._registry_lock:
                self._states.pop(incident_id, None)
                self._review_locks.pop(incident_id, None)
                self._audit.pop(incident_id, None)
            raise WorkflowError("WORKFLOW_OUTPUT_INVALID", "incident workflow returned invalid state") from exc
        self._states[incident_id] = state
        return snapshot

    async def get(self, incident_id: str) -> IncidentSnapshot:
        state = self._states.get(incident_id)
        if state is None:
            state = await self._checkpoint_state(incident_id)
            if state is not None and state.get("status") not in {"approved", "not_incident"}:
                await self._register_recovered_state(incident_id, state)
        if state is not None:
            return self._snapshot(state)
        stored = self._repository.get(incident_id)
        if stored is None:
            raise WorkflowError("INCIDENT_NOT_FOUND", "incident does not exist")
        return _stored_snapshot(stored)

    async def review(self, incident_id: str, decision: ReviewDecision) -> IncidentSnapshot:
        lock = self._review_locks.get(incident_id)
        if lock is None:
            recovered = await self._checkpoint_state(incident_id)
            if recovered is not None and recovered.get("status") == "awaiting_review":
                await self._register_recovered_state(incident_id, recovered)
                lock = self._review_locks[incident_id]
        if lock is None:
            if self._repository.get(incident_id) is not None:
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
                stored = self._store_terminal(pending_state, decision)
                self._commit_review(incident_id, pending_state, decision, stored.stored_at)
                self._pending_terminal.pop(incident_id, None)
                return self._snapshot(pending_state)
            if state.get("status") != "awaiting_review":
                raise WorkflowError("INVALID_REVIEW_TRANSITION", "incident is not awaiting review")
            if decision.action == "reanalyze":
                claim_ids = {claim.claim_id for claim in state.get("claims", [])}
                invalid_targets = set(decision.target_claim_ids) - claim_ids
                if invalid_targets:
                    raise WorkflowError("REANALYSIS_TARGET_INVALID", "re-analysis target claim does not exist")
            try:
                result = await self._runner.resume(incident_id, decision)
            except Exception as exc:
                if isinstance(exc, WorkflowError):
                    raise
                raise WorkflowError("WORKFLOW_EXECUTION_FAILED", "incident workflow could not resume") from exc
            updated = cast(IncidentState, {**state, **result})
            try:
                self._snapshot(updated)
            except Exception as exc:
                raise WorkflowError("WORKFLOW_OUTPUT_INVALID", "incident workflow returned invalid state") from exc
            if updated.get("status") in {"approved", "not_incident"}:
                try:
                    stored = self._store_terminal(updated, decision)
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
        async with self._registry_lock:
            self._states.setdefault(incident_id, state)
            self._review_locks.setdefault(incident_id, asyncio.Lock())
            self._audit.setdefault(incident_id, [])

    async def _checkpoint_state(self, incident_id: str) -> IncidentState | None:
        getter = getattr(self._runner, "get", None)
        return await getter(incident_id) if getter is not None else None

    def _store_terminal(self, state: IncidentState, decision: ReviewDecision) -> StoredReport:
        status = state.get("status")
        evidence_ids = []
        memory = state.get("video_memory")
        if memory is not None:
            evidence_ids.extend(item.evidence_id for item in memory.evidence)
        log_summary = state.get("log_evidence_summary")
        if log_summary is not None:
            evidence_ids.extend(log_summary.evidence_ids)
        report = state.get("report_narrative")
        if report is not None:
            evidence_ids.extend(report.evidence_ids)
        try:
            return self._repository.store(
                StoredReport(
                    incident_id=state["incident_id"],
                    status=cast(str, status),
                    has_log=bool(state.get("log_uri")),
                    artifact_uris=state.get("artifact_uris", {}),
                    claims=state.get("claims", []),
                    warnings=state.get("warnings", []),
                    review_audit=state.get("review_audit", []),
                    final_report=state.get("draft_report") if status == "approved" else None,
                    evidence_ids=list(dict.fromkeys(evidence_ids)),
                    reviewer=decision.reviewer,
                    decision=cast(str, decision.action),
                    reason=decision.reason,
                )
            )
        except (ReportRepositoryError, ValueError) as exc:
            raise WorkflowError(
                getattr(exc, "code", "REPORT_STORAGE_INVALID"),
                "terminal outcome could not be stored",
            ) from exc

    def _snapshot(self, state: IncidentState) -> IncidentSnapshot:
        incident_id = state["incident_id"]
        claims = state.get("claims") or (state["video_memory"].claims if state.get("video_memory") else [])
        conflicts = [claim.claim_id for claim in claims if claim.verification_status == VerificationStatus.CONTRADICTED]
        status = state.get("status", "failed")
        report = state.get("draft_report")
        memory = state.get("video_memory")
        video_summary = ""
        if memory is not None:
            video_summary = memory.video_summary or memory.global_scene
        return IncidentSnapshot(
            incident_id=incident_id,
            status=status,
            has_log=bool(state.get("log_uri")),
            video_summary=video_summary,
            artifact_uris=state.get("artifact_uris", {}),
            claims=claims,
            conflict_claim_ids=conflicts,
            auto_reanalysis_count=state.get("auto_reanalysis_count", 0),
            manual_reanalysis_count=state.get("manual_reanalysis_count", 0),
            draft_report=report if status == "awaiting_review" else None,
            final_report=report if status == "approved" else None,
            review_audit=state.get("review_audit") or self._audit.get(incident_id, []),
            warnings=state.get("warnings", []),
            error_code=state.get("error_code"),
            error_message=_safe_processing_error(state.get("error_code")) if state.get("error_message") else None,
            stored_at=self._stored_at.get(incident_id),
        )


def _stored_snapshot(stored: StoredReport) -> IncidentSnapshot:
    return IncidentSnapshot(
        incident_id=stored.incident_id,
        status=stored.status,
        has_log=stored.has_log,
        video_summary=stored.final_report.summary if stored.final_report is not None else "",
        artifact_uris=stored.artifact_uris,
        claims=stored.claims,
        conflict_claim_ids=[
            claim.claim_id for claim in stored.claims if claim.verification_status == VerificationStatus.CONTRADICTED
        ],
        warnings=stored.warnings,
        final_report=stored.final_report,
        review_audit=stored.review_audit
        or [ReviewAuditEntry(action=stored.decision, reviewer=stored.reviewer, reason=stored.reason)],
        stored_at=stored.stored_at,
    )


def _safe_processing_error(code: str | None) -> str:
    return {
        "OPENAI_AUTHENTICATION_FAILED": "OpenAI từ chối API key. Kiểm tra OPENAI_API_KEY rồi khởi động lại FastAPI.",
        "OPENAI_PERMISSION_DENIED": "API key không có quyền dùng model verification đã cấu hình.",
        "OPENAI_RATE_LIMITED": (
            "Phân tích video và cắt clip đã hoàn tất, nhưng bước OpenAI verification hết quota hoặc đang "
            "rate-limit. Kiểm tra Billing/Usage rồi thử lại với incident ID mới."
        ),
        "OPENAI_VERIFICATION_TIMEOUT": "OpenAI verification quá thời gian chờ. Thử lại hoặc tăng VERIFICATION_TIMEOUT_S.",
        "OPENAI_CONNECTION_FAILED": "Backend không kết nối được tới OpenAI. Kiểm tra mạng/proxy của máy chạy FastAPI.",
        "OPENAI_VERIFICATION_REQUEST_INVALID": (
            "OpenAI từ chối model hoặc structured request verification. Kiểm tra VERIFICATION_MODEL_NAME."
        ),
        "VERIFICATION_STRUCTURED_OUTPUT_INVALID": "OpenAI trả kết quả verification không đúng schema.",
        "VLM_EVIDENCE_REFERENCE_INVALID": (
            "VLM trả evidence_id không tồn tại trong các frame đã phân tích. Hãy chạy lại bằng incident ID mới."
        ),
    }.get(code, "incident processing failed")
