"""STEP 5 - Register Braintrust online scorers and grade AWS AgentCore traces.

Does not re-run agents. Scores come from traces exported during step 3
(OTLP to api.braintrust.dev/otel). Idle timeout is long enough for the
streaming metadata span to land.

Usage:  python step5_score_braintrust.py
Output: results/<provider>/braintrust_scores.json
"""
import json
import os
import time

from loan_agents import data, models
from scoring import cases, runs, trace_scores

assert os.getenv("BRAINTRUST_API_KEY"), "Add BRAINTRUST_API_KEY to .env (free account at braintrust.dev)."
PROJECT = "loan-agents"
ALL = {c["id"]: c for c in cases.load()}
DATASET = "loan-agent-test-cases-v1" if len(ALL) == 60 else f"loan-agent-test-cases-{len(ALL)}"
SAVED = runs.load()
assert SAVED, "No invoke log. Run step3_run_agents.py first."

registration = trace_scores.register_braintrust_evaluators()
print(f"Braintrust evaluators: registered={registration.get('registered')} ({registration.get('reason', 'ok')})")

GRADES: dict = {}
t0 = time.time()
for cid, case in ALL.items():
    log = SAVED.get(cid)
    if not log:
        GRADES[cid] = dict(trace_scores.NOT_RUN)
        continue
    spans = trace_scores.fetch_braintrust_spans(cid, log.get("session_id") or "")
    graded = trace_scores.grade_from_spans(case, spans)
    if graded is None:
        GRADES[cid] = dict(trace_scores.NOT_RUN)
        if log.get("error"):
            GRADES[cid]["ai_judge"] = {"score": 0.0, "reason": f"agent error: {log['error'][:200]}"}
            GRADES[cid]["verdict"] = "FAIL"
    else:
        GRADES[cid] = graded

seconds = round(time.time() - t0, 1)
table = runs.gate_table(GRADES, list(ALL.values()))
out = runs.runs_file().parent / "braintrust_scores.json"
out.write_text(json.dumps({
    "platform": "Braintrust",
    "model": models.agent_model_name(),
    "judge": models.JUDGE_MODEL,
    "dataset": DATASET,
    "project": PROJECT,
    "evaluators": registration,
    "grading_seconds": seconds,
    "gates": table,
    "cases": GRADES,
}, indent=1, default=str), encoding="utf-8")
for r in table:
    print(f"{r['gate']:45} pass {r['pass']} fail {r['fail']} review {r['review']}  -> {r['gate_verdict']}")
print(f"-> {out.relative_to(data.HERE)}   (graded in {seconds}s from Braintrust traces)")
