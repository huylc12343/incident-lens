"""Run the P-207 test suite by product capability.

Each group runs in a separate pytest process. This keeps failures isolated and
makes the evaluation report easier to map back to a product capability.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence

TEST_GROUPS: dict[str, tuple[str, ...]] = {
    "agent-routing": (
        "tests/test_agents/test_incident_routing.py",
        "tests/test_agents/test_incident_node.py",
        "tests/test_agents/test_review_node.py",
        "tests/test_agents/test_review_edits.py",
        "tests/test_agents/test_incident_graph_e2e.py",
    ),
    "api-incident": (
        "tests/test_api/test_incidents.py",
        "tests/test_api/test_routes.py",
    ),
    "video-cv": (
        "tests/test_cv_pipeline.py",
        "tests/test_services/test_qwen_vlm.py",
        "tests/test_services/test_ground_truth.py",
    ),
    "verification-reporting": (
        "tests/test_services/test_verification.py",
        "tests/test_services/test_reporting.py",
        "tests/test_services/test_claim_log_summary.py",
        "tests/test_services/test_report_repository.py",
    ),
    "upload-media-memory": (
        "tests/test_services/test_uploads.py",
        "tests/test_services/test_media.py",
        "tests/test_services/test_video_memory.py",
        "tests/test_services/test_video_memory_evidence_consistency.py",
    ),
    "prompts-reanalysis": (
        "tests/test_prompts",
        "tests/test_agents/test_auto_reanalysis_toggle.py",
    ),
    "metrics": (
        "tests/test_eval/test_metrics.py",
        "tests/test_services/test_model_observability.py",
    ),
    "langsmith": (
        "tests/test_services/test_langsmith_tracing.py",
        "tests/test_agents/test_incident_tracing.py",
    ),
}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group",
        action="append",
        choices=["all", *TEST_GROUPS],
        help="Test group to run. Repeat the option for multiple groups; default: all.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Use compact pytest output instead of verbose test names.",
    )
    return parser.parse_args(argv)


def _selected_groups(requested: list[str] | None) -> list[str]:
    if not requested or "all" in requested:
        return list(TEST_GROUPS)
    return list(dict.fromkeys(requested))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    selected = _selected_groups(args.group)
    failures: list[str] = []

    for group in selected:
        print(f"\n=== {group} ===", flush=True)
        verbosity = "-q" if args.quiet else "-v"
        command = [sys.executable, "-m", "pytest", *TEST_GROUPS[group], verbosity]
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            failures.append(group)

    if failures:
        print(f"\nFailed groups: {', '.join(failures)}", file=sys.stderr)
        return 1

    print(f"\nAll {len(selected)} selected test groups passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
