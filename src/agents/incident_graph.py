"""Complete incident LangGraph and its persistent async runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.agents.incident_routing import route_after_verification
from src.agents.incident_state import IncidentState
from src.agents.nodes.incident import (
    ChartWorkflowService,
    LogWorkflowService,
    MediaWorkflowService,
    align_and_verify_claims_node,
    analyze_log_node,
    analyze_video_node,
    auto_reanalyze_node,
    build_draft_report_node,
    cut_incident_video_node,
    manual_reanalyze_node,
)
from src.agents.nodes.review import human_review_interrupt_node
from src.models.api import ReviewDecision
from src.models.incidents import ReportService, VerificationService
from src.services.model_observability import ModelActivityRegistry
from src.services.video_memory import VideoMemoryWorkflow


@dataclass(frozen=True)
class IncidentGraphDependencies:
    media: MediaWorkflowService
    video_workflow: VideoMemoryWorkflow
    log_analysis: LogWorkflowService
    charts: ChartWorkflowService
    verification: VerificationService
    report: ReportService
    artifact_dir: str
    timestamp_tolerance_s: float = 0.5
    reanalysis_prompt_version: str = "v1"
    auto_reanalysis_enabled: bool = True
    cleanup_remote_resources: bool = True
    observability: ModelActivityRegistry = field(default_factory=ModelActivityRegistry)


def build_incident_graph(*, dependencies: IncidentGraphDependencies, checkpointer: Any) -> Any:
    graph = StateGraph(IncidentState)

    async def analyze_video(state: IncidentState) -> dict[str, object]:
        result = await analyze_video_node(state, media=dependencies.media, workflow=dependencies.video_workflow)
        return _with_model_activities(state, result, dependencies.observability)

    async def cut_video(state: IncidentState) -> dict[str, object]:
        return await cut_incident_video_node(state, media=dependencies.media, workflow=dependencies.video_workflow)

    async def analyze_log(state: IncidentState) -> dict[str, object]:
        return await analyze_log_node(
            state,
            log_analysis=dependencies.log_analysis,
            charts=dependencies.charts,
            artifact_dir=dependencies.artifact_dir,
        )

    async def verify(state: IncidentState) -> dict[str, object]:
        result = await align_and_verify_claims_node(
            state,
            verification=dependencies.verification,
            timestamp_tolerance_s=dependencies.timestamp_tolerance_s,
        )
        return _with_model_activities(state, result, dependencies.observability)

    async def auto_reanalyze(state: IncidentState) -> dict[str, object]:
        result = await auto_reanalyze_node(
            state,
            media=dependencies.media,
            workflow=dependencies.video_workflow,
            prompt_version=dependencies.reanalysis_prompt_version,
        )
        return _with_model_activities(state, result, dependencies.observability)

    async def manual_reanalyze(state: IncidentState) -> dict[str, object]:
        result = await manual_reanalyze_node(
            state,
            media=dependencies.media,
            workflow=dependencies.video_workflow,
            prompt_version=dependencies.reanalysis_prompt_version,
        )
        return _with_model_activities(state, result, dependencies.observability)

    async def build_report(state: IncidentState) -> dict[str, object]:
        result = await build_draft_report_node(state, report=dependencies.report)
        return _with_model_activities(state, result, dependencies.observability)

    async def cleanup(state: IncidentState) -> dict[str, object]:
        handles = state.get("remote_media_handles", [])
        if handles and dependencies.cleanup_remote_resources:
            try:
                await dependencies.video_workflow.vlm.release_remote_resources(handles)
            except Exception:
                warnings = [*state.get("warnings", []), "Remote media cleanup failed."]
                return {"warnings": list(dict.fromkeys(warnings)), "remote_media_handles": []}
        return {"remote_media_handles": []}

    async def after_step(state: IncidentState) -> Literal["continue", "cleanup"]:
        return "cleanup" if state.get("status") == "failed" else "continue"

    async def after_clip(state: IncidentState) -> Literal["analyze_log", "draft_report", "cleanup"]:
        if state.get("status") == "failed":
            return "cleanup"
        return "analyze_log" if state.get("log_uri") else "draft_report"

    async def after_verification(state: IncidentState) -> Literal["auto_reanalyze", "draft_report", "cleanup"]:
        if state.get("status") == "failed":
            return "cleanup"
        return route_after_verification({**state, "auto_reanalysis_enabled": dependencies.auto_reanalysis_enabled})

    async def after_review(state: IncidentState) -> Literal["review", "manual_reanalyze", "cleanup"]:
        if state.get("status") in {"approved", "not_incident", "failed"}:
            return "cleanup"
        if state.get("last_review_action") == "edit":
            return "review"
        if state.get("last_review_action") == "reanalyze":
            return "manual_reanalyze"
        return "review"

    async def after_manual(state: IncidentState) -> Literal["manual_verify", "draft_report", "cleanup"]:
        if state.get("status") == "failed":
            return "cleanup"
        return "manual_verify" if state.get("log_uri") else "draft_report"

    graph.add_node("analyze_video", analyze_video)
    graph.add_node("cut_incident_video", cut_video)
    graph.add_node("analyze_log", analyze_log)
    graph.add_node("verify", verify)
    graph.add_node("auto_reanalyze", auto_reanalyze)
    graph.add_node("manual_reanalyze", manual_reanalyze)
    graph.add_node("manual_verify", verify)
    graph.add_node("draft_report", build_report)
    graph.add_node("review", human_review_interrupt_node)
    graph.add_node("cleanup", cleanup)

    graph.add_edge(START, "analyze_video")
    graph.add_conditional_edges("analyze_video", after_step, {"continue": "cut_incident_video", "cleanup": "cleanup"})
    graph.add_conditional_edges("cut_incident_video", after_clip)
    graph.add_conditional_edges("analyze_log", after_step, {"continue": "verify", "cleanup": "cleanup"})
    graph.add_conditional_edges("verify", after_verification)
    graph.add_conditional_edges("auto_reanalyze", after_step, {"continue": "verify", "cleanup": "cleanup"})
    graph.add_conditional_edges("draft_report", after_step, {"continue": "review", "cleanup": "cleanup"})
    graph.add_conditional_edges("review", after_review)
    graph.add_conditional_edges("manual_reanalyze", after_manual)
    graph.add_conditional_edges("manual_verify", after_step, {"continue": "draft_report", "cleanup": "cleanup"})
    graph.add_edge("cleanup", END)
    return graph.compile(checkpointer=checkpointer)


class LangGraphIncidentRunner:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    async def start(self, state: IncidentState) -> IncidentState:
        result = await self._graph.ainvoke(state, self.thread_config(state["incident_id"]))
        return self._public_state(result)

    async def resume(self, incident_id: str, decision: ReviewDecision) -> IncidentState:
        result = await self._graph.ainvoke(
            Command(resume=decision.model_dump(mode="json")),
            self.thread_config(incident_id),
        )
        return self._public_state(result)

    async def get(self, incident_id: str) -> IncidentState | None:
        snapshot = await self._graph.aget_state(self.thread_config(incident_id))
        return self._public_state(snapshot.values) if snapshot.values else None

    async def list_incident_ids(self) -> list[str]:
        incident_ids: list[str] = []
        seen: set[str] = set()
        async for checkpoint in self._graph.checkpointer.alist(None):
            incident_id = checkpoint.config.get("configurable", {}).get("thread_id")
            if isinstance(incident_id, str) and incident_id not in seen:
                incident_ids.append(incident_id)
                seen.add(incident_id)
        return incident_ids

    async def delete(self, incident_id: str) -> None:
        await self._graph.checkpointer.adelete_thread(incident_id)

    @staticmethod
    def thread_config(incident_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": incident_id}}

    @staticmethod
    def _public_state(value: dict[str, Any]) -> IncidentState:
        return {key: item for key, item in value.items() if not key.startswith("__")}


def _with_model_activities(
    state: IncidentState,
    result: dict[str, object],
    observability: ModelActivityRegistry,
) -> dict[str, object]:
    incident_id = state.get("incident_id", "")
    activities = observability.list(incident_id)
    return {**result, "model_activities": activities or state.get("model_activities", [])}
