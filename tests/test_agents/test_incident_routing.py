import pytest

from src.agents.incident_routing import route_after_verification
from src.models.incidents import ClaimVerification, VerificationResult, VerificationStatus


def _verification(status: VerificationStatus) -> VerificationResult:
    return VerificationResult(
        results=[ClaimVerification(claim_id="claim-1", status=status, reason="Checked against log")]
    )


def test_routes_first_conflict_to_auto_reanalysis() -> None:
    route = route_after_verification(
        {"verification": _verification(VerificationStatus.CONTRADICTED), "auto_reanalysis_count": 0}
    )

    assert route == "auto_reanalyze"


@pytest.mark.parametrize("count", [1, 2])
def test_routes_to_report_after_auto_retry_limit(count: int) -> None:
    route = route_after_verification(
        {"verification": _verification(VerificationStatus.CONTRADICTED), "auto_reanalysis_count": count}
    )

    assert route == "draft_report"


def test_routes_supported_claims_to_report() -> None:
    assert (
        route_after_verification(
            {"verification": _verification(VerificationStatus.SUPPORTED), "auto_reanalysis_count": 0}
        )
        == "draft_report"
    )


def test_missing_verification_degrades_to_report() -> None:
    assert route_after_verification({}) == "draft_report"
