import json

from loan_agents import models, runtime, tools


def test_handle_event_returns_tool_calls_and_usage(monkeypatch):
    models.PROVIDER = "dryrun"
    tools.CALLS.clear()
    result = runtime.handle_event({
        "prompt": "Run the default risk screen.",
        "session_id": "sess-av-g18-x01-padded-to-33chars",
        "case_id": "AV-G18-X01",
        "fault": None,
    })
    assert "tool_calls" in result
    assert "input_tokens" in result
    assert result["session_id"]
    assert len(result["session_id"]) >= 33
    assert result["error"] == ""
    assert "dry run" in result["answer"]


def test_fault_payload_fails_named_tool():
    tools.CALLS.clear()
    tools.FAULT = "text_to_sql_down"
    out = json.loads(tools.recorded(tools.text_to_sql)("what is min_score for 100829595540?"))
    tools.FAULT = None
    assert "error" in out
    assert "text_to_sql" in out["error"]
    assert tools.CALLS[-1]["tool"] == "text_to_sql"
