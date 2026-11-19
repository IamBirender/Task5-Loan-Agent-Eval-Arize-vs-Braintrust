"""STEP 4 - Register Arize online evaluators and grade AWS AgentCore traces.

Does not re-run agents. Scores come from traces exported during step 3
(OpenInference OTLP to otlp.arize.com). The step-3 JSONL is only an invoke log.

Usage:  python step4_score_arize.py
Output: results/<provider>/arize_scores.json
"""
import json
import os
import time

os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

from loan_agents import data, models
from scoring import cases, runs, trace_scores

SPACE = os.environ.get("ARIZE_SPACE_ID", "")
ALL = {c["id"]: c for c in cases.load()}
SAVED = runs.load()
assert SAVED, "No invoke log. Run step3_run_agents.py first."
DATASET = "loan-agent-test-cases-v1" if len(ALL) == 60 else f"loan-agent-test-cases-{len(ALL)}"

registration = trace_scores.register_arize_evaluators()
print(f"Arize evaluators: registered={registration.get('registered')} ({registration.get('reason', 'ok')})")

GRADES: dict = {}
t0 = time.time()
for cid, case in ALL.items():
    log = SAVED.get(cid)
    if not log:
        GRADES[cid] = dict(trace_scores.NOT_RUN)
        continue
    spans = trace_scores.fetch_arize_spans(cid, log.get("session_id") or "")
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
out = runs.runs_file().parent / "arize_scores.json"
out.write_text(json.dumps({
    "platform": "Arize AX",
    "model": models.agent_model_name(),
    "judge": models.JUDGE_MODEL,
    "dataset": DATASET,
    "evaluators": registration,
    "grading_seconds": seconds,
    "gates": table,
    "cases": GRADES,
}, indent=1, default=str), encoding="utf-8")
for r in table:
    print(f"{r['gate']:45} pass {r['pass']} fail {r['fail']} review {r['review']}  -> {r['gate_verdict']}")
print(f"-> {out.relative_to(data.HERE)}   (graded in {seconds}s from Arize traces)")
