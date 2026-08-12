from src.agents.incident_routing import route_after_verification
from src.models.incidents import ClaimVerification, VerificationResult, VerificationStatus


def test_disabled_auto_reanalysis_routes_conflicting_claims_to_report() -> None:
    verification = VerificationResult(
        results=[
            ClaimVerification(
                claim_id="claim-1",
                status=VerificationStatus.CONTRADICTED,
                reason="Log không phản ánh claim.",
            )
        ]
    )

    assert route_after_verification(
        {
            "verification": verification,
            "auto_reanalysis_count": 0,
            "auto_reanalysis_enabled": False,
        }
    ) == "draft_report"
