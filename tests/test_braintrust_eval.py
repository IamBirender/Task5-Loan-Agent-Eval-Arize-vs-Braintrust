from scoring import braintrust_eval


class _Dataset:
    def __init__(self):
        self.rows = []

    def insert(self, **row):
        self.rows.append(row)

    def flush(self):
        return None

    def __iter__(self):
        return iter(self.rows)


class _Summary:
    experiment_url = "https://www.braintrust.dev/app/x/p/loan-agents/experiments/t"


class _Braintrust:
    def __init__(self):
        self.datasets = {}
        self.evals = []
        self.dataset = None
        self.dataset_name = None
        self.eval_kwargs = None
        self.project = None

    def init_dataset(self, project, name):
        self.project = project
        ds = _Dataset()
        self.datasets[name] = ds
        self.dataset = ds
        self.dataset_name = name
        return ds

    def Eval(self, project, **kwargs):
        rec = {"project": project, **kwargs}
        self.evals.append(rec)
        self.eval_kwargs = rec
        for row in kwargs["data"]:
            out = kwargs["task"](row["input"])
            for scorer in kwargs["scores"]:
                scorer(row["input"], out, row.get("expected"))

        class _Result:
            summary = _Summary()

        return _Result()


def _case(cid: str) -> dict:
    return {
        "id": cid,
        "input": f"question {cid}",
        "expected": "8 loans",
        "gate": "G1 · Prompt & Config Validation",
        "agent": "Supervisor Agent",
        "method": "Deterministic",
        "guidelines": [],
        "expected_tools": [],
    }


def _saved(cid: str) -> dict:
    return {
        cid: {
            "answer": "8 loans",
            "tool_calls": [],
            "error": "",
            "seconds": 1.2,
            "tokens": 10,
            "input_tokens": 6,
            "output_tokens": 4,
            "est_cost_usd": 0.01,
            "model": "test",
        }
    }


def test_chunk_names():
    assert braintrust_eval.chunk_name(1, 50) == "T1-T50"
    assert braintrust_eval.chunk_name(51, 100) == "T51-T100"
    assert braintrust_eval.chunk_name(2451, 2500) == "T2451-T2500"
    parts = braintrust_eval.chunk_cases([{"id": i} for i in range(2500)])
    assert len(parts) == 50
    assert parts[0][0] == "T1-T50"
    assert parts[-1][0] == "T2451-T2500"
    assert [len(p) for _, p in parts] == [50] * 50


def test_dataset_name():
    assert braintrust_eval.dataset_name(2500) == "T1-T2500"


def test_publish_creates_dataset_and_experiment(monkeypatch):
    fake = _Braintrust()
    monkeypatch.setattr(
        braintrust_eval.runs,
        "grade",
        lambda case, run: {
            "tool_check": {"score": 1.0},
            "facts_check": {"score": 1.0},
            "policy_check": None,
            "ai_judge": {"score": 1.0, "reason": "ok"},
            "verdict": "PASS",
        },
    )
    out = braintrust_eval.publish(
        [_case("AV-G1-001")],
        _saved("AV-G1-001"),
        bt=fake,
        experiment_name="test-exp",
    )
    assert fake.project == "loan-agents"
    assert fake.dataset_name == "T1-T1"
    assert fake.dataset.rows[0]["id"] == "AV-G1-001"
    assert fake.eval_kwargs["experiment_name"] == "test-exp"
    assert out["experiment_url"].endswith("/experiments/t")
    assert out["grades"]["AV-G1-001"]["verdict"] == "PASS"


def test_publish_splits_into_fifty_named_chunks(monkeypatch):
    fake = _Braintrust()
    monkeypatch.setattr(
        braintrust_eval.runs,
        "grade",
        lambda case, run: {
            "tool_check": {"score": 1.0},
            "facts_check": {"score": 1.0},
            "policy_check": None,
            "ai_judge": {"score": 1.0, "reason": "ok"},
            "verdict": "PASS",
        },
    )
    cases = [_case(f"AV-G1-X{i:03d}") for i in range(1, 101)]
    saved = {}
    for c in cases:
        saved.update(_saved(c["id"]))
    out = braintrust_eval.publish(cases, saved, bt=fake, chunk_size=50)
    assert list(fake.datasets) == ["T1-T50", "T51-T100"]
    assert [e["experiment_name"] for e in fake.evals] == ["T1-T50", "T51-T100"]
    assert [c["dataset"] for c in out["chunks"]] == ["T1-T50", "T51-T100"]
    assert out["chunks"][0]["n"] == 50
    assert out["chunks"][1]["n"] == 50
    assert len(out["grades"]) == 100
