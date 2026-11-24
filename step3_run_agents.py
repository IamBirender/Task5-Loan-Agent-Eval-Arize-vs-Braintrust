"""STEP 3 - Invoke the AgentCore specialists / Strands supervisor once per case.

This writes an invoke log (case id, error, session id, trace ids). Arize and
Braintrust score the traces those agents emit; this JSONL is not the grading source.

Cases come from scoring.cases.load() (spreadsheet + extra_test_cases.json).

Cases run in parallel (default 8 workers). Local stand-ins stay in-process;
only the case loop is concurrent. Use --workers 1 for the old sequential path.

Usage:  python step3_run_agents.py
        python step3_run_agents.py --workers 8
        python step3_run_agents.py --limit 3
        python step3_run_agents.py --ids AV-G1-001 AV-G4-002
        python step3_run_agents.py --fresh
        ONLY_SENIOR_CASES=1 python step3_run_agents.py
        LOAN_EVAL_WORKERS=4 python step3_run_agents.py
Output: results/<provider>-<version>/agent_runs.jsonl
"""
import argparse
import json
import threading

from loan_agents import data, models, runner, telemetry
from scoring import cases, runs

ap = argparse.ArgumentParser()
ap.add_argument("--ids", nargs="*")
ap.add_argument("--limit", type=int)
ap.add_argument("--workers", type=int, default=None, help="parallel cases (default 8, or LOAN_EVAL_WORKERS)")
ap.add_argument("--fresh", action="store_true", help="delete earlier results and run everything again")
args = ap.parse_args()

telemetry.setup_tracing()
print(
    f"otel: arize={telemetry.EXPORT['arize']} braintrust={telemetry.EXPORT['braintrust']}"
    + (f"  arize_error={telemetry.EXPORT['arize_error']}" if telemetry.EXPORT["arize_error"] else "")
    + (f"  braintrust_error={telemetry.EXPORT['braintrust_error']}" if telemetry.EXPORT["braintrust_error"] else "")
)
out = runs.runs_file()
if args.fresh:
    out.unlink(missing_ok=True)
done = {i for i, r in runs.load().items() if not r["error"]}
todo = [c for c in cases.load() if (not args.ids or c["id"] in args.ids) and c["id"] not in done][: args.limit]
workers = runner.worker_count(args.workers)
print(
    f"model: {models.PROVIDER} / {models.agent_model_name()}   cases to run: {len(todo)}   "
    f"workers: {workers}   (already done: {len(done)})"
)

_write = threading.Lock()
_n = 0
_n_lock = threading.Lock()


def _log(rec: dict) -> None:
    global _n
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
    with _write:
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log, default=str) + "\n")
    with _n_lock:
        _n += 1
        n = _n
    print(
        f"[{n}/{len(todo)}] {rec['id']:10} {rec['seconds']:6.1f}s  "
        f"tools={[c['tool'] for c in rec['tool_calls']]}"
        + (f"  ERROR {rec['error'][:150]}" if rec["error"] else ""),
        flush=True,
    )


runner.run_cases(todo, workers=workers, on_result=_log)
telemetry.flush()
print(f"-> {out.relative_to(data.HERE)}")
