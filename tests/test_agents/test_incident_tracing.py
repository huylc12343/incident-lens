from unittest.mock import AsyncMock

import pytest

from src.agents.incident_graph import LangGraphIncidentRunner


@pytest.mark.asyncio
async def test_runner_adds_trace_metadata_without_changing_graph_result() -> None:
    expected = {"incident_id": "INC-TRACE", "status": "awaiting_review"}
    graph = AsyncMock()
    graph.ainvoke.return_value = expected
    runner = LangGraphIncidentRunner(graph)

    result = await runner.start({"incident_id": "INC-TRACE"})

    assert result == expected
    config = graph.ainvoke.await_args.args[1]
    assert config["configurable"] == {"thread_id": "INC-TRACE"}
    assert config["metadata"] == {
        "thread_id": "INC-TRACE",
        "incident_id": "INC-TRACE",
        "workflow_phase": "start",
    }
    assert config["tags"] == ["workflow:incident-analysis", "phase:start"]
    assert config["run_name"] == "incident-analysis"
