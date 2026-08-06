"""Deterministic routing decisions for incident verification."""

from typing import Literal

from src.agents.incident_state import IncidentState
from src.models.incidents import VerificationStatus


def route_after_verification(state: IncidentState) -> Literal["auto_reanalyze", "draft_report"]:
    verification = state.get("verification")
    if verification is None:
        return "draft_report"
    has_conflict = any(result.status == VerificationStatus.CONTRADICTED for result in verification.results)
    if has_conflict and state.get("auto_reanalysis_count", 0) < 1:
        return "auto_reanalyze"
    return "draft_report"
