"""STEP 5 - Upload the dataset, run a Braintrust experiment, register online scorers.

Does not re-run agents. Scores come from the step-3 invoke log (same 4 scorers as
Arize). OTLP traces from step 3, if exported, show under project Logs.

Usage:  python step5_score_braintrust.py
        python step5_score_braintrust.py --trace 3
Output: results/<provider>/braintrust_scores.json
"""
import argparse
import json
import os

from loan_agents import data, models, runner, telemetry
from scoring import braintrust_eval, cases, runs, trace_scores

ap = argparse.ArgumentParser()
ap.add_argument("--trace", type=int, default=0, help="also re-run this many cases live so traces show in Logs")
args = ap.parse_args()

assert os.getenv("BRAINTRUST_API_KEY"), "Add BRAINTRUST_API_KEY to .env (free account at braintrust.dev)."
PROJECT = "loan-agents"
ALL = {c["id"]: c for c in cases.load()}
SAVED = runs.load()
assert SAVED, "No invoke log. Run step3_run_agents.py first."

registration = trace_scores.register_braintrust_evaluators()
reason = registration.get("reason") or registration.get("llm_warning") or "ok"
print(f"Braintrust evaluators: registered={registration.get('registered')} ({reason})")
if registration.get("registered"):
    print(
        f"  project={registration.get('project_id')}  "
        f"functions={[f.get('name') for f in registration.get('functions') or []]}"
    )

published = braintrust_eval.publish(ALL, SAVED)
GRADES = published["grades"]
print(f"Braintrust dataset {published['dataset']}: {len(ALL)} cases")
print(f"Braintrust experiment: {published.get('experiment_url') or published['experiment_name']}")

if args.trace:
    telemetry.setup_tracing()
    live = [c for c in ALL.values() if c["id"] in SAVED and not SAVED[c["id"]].get("error")][: args.trace]
    for case in live:
        rec = runner.run_case(case)
        print(f"traced {case['id']} -> Braintrust project '{PROJECT}' logs ({rec['seconds']}s)")
    telemetry.flush()

table = runs.gate_table(GRADES, list(ALL.values()))
out = runs.runs_file().parent / "braintrust_scores.json"
out.write_text(json.dumps({
    "platform": "Braintrust",
    "model": models.agent_model_name(),
    "judge": models.JUDGE_MODEL,
    "dataset": published["dataset"],
    "project": PROJECT,
    "experiment_url": published.get("experiment_url"),
    "evaluators": registration,
    "grading_seconds": published["seconds"],
    "gates": table,
    "cases": GRADES,
}, indent=1, default=str), encoding="utf-8")
for row in table:
    print(f"{row['gate']:45} pass {row['pass']} fail {row['fail']} review {row['review']}  -> {row['gate_verdict']}")
print(f"-> {out.relative_to(data.HERE)}   (graded in {published['seconds']}s)  {published.get('experiment_url') or ''}")
print("UI: Braintrust project loan-agents -> Datasets and Experiments. Logs = live OTEL traces from step 3.")
