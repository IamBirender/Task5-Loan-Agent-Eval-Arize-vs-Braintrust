import time
from concurrent.futures import ThreadPoolExecutor

from loan_agents import context, models, runner, tools


def _case(cid: str, fault=None) -> dict:
    return {
        "id": cid,
        "agent": "Pool Screening Agent",
        "turns": [f"prompt {cid}"],
        "input": f"prompt {cid}",
        "session_id": f"sess-{cid.lower()}-padded-to-33-chars",
        "fault": fault,
        "gate": "G1",
        "method": "Deterministic",
        "expected": "",
        "guidelines": [],
        "expected_tools": [],
        "forbidden": [],
    }


def test_calls_and_fault_isolated_across_threads():
    def worker(tag: str, fault: str):
        tools.CALLS.clear()
        context.fault.set(fault)
        tools.CALLS.append({"tool": tag, "output": fault})
        time.sleep(0.05)
        return [c["tool"] for c in tools.CALLS], tools.current_fault()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(worker, f"t{i}", f"fault_{i}") for i in range(8)]
        results = [f.result() for f in futs]
    for i, (names, fault) in enumerate(results):
        assert names == [f"t{i}"], (i, names)
        assert fault == f"fault_{i}", (i, fault)


def test_parallel_dryrun_cases_keep_their_ids(monkeypatch):
    monkeypatch.setattr(models, "PROVIDER", "dryrun")
    cases = [_case(f"AV-G1-P{i:02d}") for i in range(1, 7)]
    recs = runner.run_cases(cases, workers=4)
    assert {r["id"] for r in recs} == {c["id"] for c in cases}
    by_id = {r["id"]: r for r in recs}
    for case in cases:
        rec = by_id[case["id"]]
        assert rec["id"] in rec["answer"]
        assert rec["error"] == ""
    assert len({r["session_id"] for r in recs}) == len(recs)


def test_worker_count_env_and_flag(monkeypatch):
    monkeypatch.delenv("LOAN_EVAL_WORKERS", raising=False)
    assert runner.worker_count(None) == runner.DEFAULT_WORKERS
    assert runner.worker_count(1) == 1
    assert runner.worker_count(16) == 16
    monkeypatch.setenv("LOAN_EVAL_WORKERS", "4")
    assert runner.worker_count(None) == 4
    assert runner.worker_count(2) == 2
