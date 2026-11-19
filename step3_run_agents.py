"""STEP 3 - Invoke the AgentCore specialists / Strands supervisor once per case.

This writes an invoke log (case id, error, session id, trace ids). Arize and
Braintrust score the traces those agents emit; this JSONL is not the grading source.

Usage:  python step3_run_agents.py
        python step3_run_agents.py --limit 3
        python step3_run_agents.py --ids AV-G1-001 AV-G4-002
        python step3_run_agents.py --fresh
Output: results/<provider>-<version>/agent_runs.jsonl
"""
import argparse
import json

from loan_agents import data, models, runner, telemetry
from scoring import cases, runs

ap = argparse.ArgumentParser()
ap.add_argument("--ids", nargs="*")
ap.add_argument("--limit", type=int)
ap.add_argument("--fresh", action="store_true", help="delete earlier results and run everything again")
args = ap.parse_args()

telemetry.setup_tracing()
out = runs.runs_file()
if args.fresh:
    out.unlink(missing_ok=True)
done = {i for i, r in runs.load().items() if not r["error"]}
todo = [c for c in cases.load() if (not args.ids or c["id"] in args.ids) and c["id"] not in done][: args.limit]
print(f"model: {models.PROVIDER} / {models.agent_model_name()}   cases to run: {len(todo)}   (already done: {len(done)})")

for n, case in enumerate(todo, 1):
    rec = runner.run_case(case)
    log = {
        "id": rec["id"],
        "agent": rec["agent"],
        "model": rec["model"],
        "provider": rec["provider"],
        "seconds": rec["seconds"],
        "error": rec["error"],
        "session_id": rec.get("session_id"),
        "arize_trace_id": rec.get("arize_trace_id"),
        "braintrust_trace_id": rec.get("braintrust_trace_id"),
        "tokens": rec.get("tokens"),
        "input_tokens": rec.get("input_tokens"),
        "output_tokens": rec.get("output_tokens"),
        "est_cost_usd": rec.get("est_cost_usd"),
        "tables_intact": rec.get("tables_intact"),
        "tool_calls": rec.get("tool_calls"),
        "answer": rec.get("answer"),
    }
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log, default=str) + "\n")
    print(f"[{n}/{len(todo)}] {case['id']:10} {rec['seconds']:6.1f}s  tools={[c['tool'] for c in rec['tool_calls']]}"
          + (f"  ERROR {rec['error'][:150]}" if rec["error"] else ""), flush=True)
print(f"-> {out.relative_to(data.HERE)}")
