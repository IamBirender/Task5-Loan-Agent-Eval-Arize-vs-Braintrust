from loan_agents.telemetry import run_from_span_attrs
from scoring import evaluator_source, trace_scores


def test_run_from_span_attrs():
    attrs = {
        "loan.case_id": "AV-G19-X01",
        "output.value": "indicative net loss of $59,160.03",
        "loan.tool_calls": '[{"tool": "loan_performance", "args": {}, "output": "{}"}]',
        "llm.token_count.total": 120,
        "llm.token_count.prompt": 80,
        "llm.token_count.completion": 40,
        "loan.seconds": 1.2,
        "loan.tables_intact": True,
        "loan.error": "",
    }
    run = run_from_span_attrs(attrs)
    assert run["answer"].startswith("indicative")
    assert run["tool_calls"][0]["tool"] == "loan_performance"
    assert run["tokens"] == 120
    assert run["tables_intact"] is True


def test_spans_to_run():
    spans = [{"attributes": {"loan.case_id": "AV-G1-001", "output.value": "ok", "loan.tool_calls": "[]"}}]
    run = trace_scores.spans_to_run(spans)
    assert run["answer"] == "ok"


def test_evaluator_source_includes_checks():
    src = evaluator_source.arize_evaluator_source()
    assert "def tool_check" in src
    assert "def eval_verdict" in src
    assert "def facts_check" in src


def test_register_evaluators_without_keys():
    arize = trace_scores.register_arize_evaluators(space_id="", api_key="")
    assert arize["registered"] is False
    bt = trace_scores.register_braintrust_evaluators(api_key="")
    assert bt["registered"] is False
