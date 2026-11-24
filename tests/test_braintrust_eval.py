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
        self.dataset = _Dataset()
        self.eval_kwargs = None

    def init_dataset(self, project, name):
        self.project = project
        self.dataset_name = name
        return self.dataset

    def Eval(self, project, **kwargs):
        self.eval_kwargs = {"project": project, **kwargs}
        for row in kwargs["data"]:
            out = kwargs["task"](row["input"])
            for scorer in kwargs["scores"]:
                scorer(row["input"], out, row.get("expected"))

        class _Result:
            summary = _Summary()

        return _Result()


def test_dataset_name():
    assert braintrust_eval.dataset_name(60) == "loan-agent-test-cases-v1"
    assert braintrust_eval.dataset_name(2260) == "loan-agent-test-cases-2260"


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
    case = {
        "id": "AV-G1-001",
        "input": "Give me the pool summary.",
        "expected": "8 loans",
        "gate": "G1 · Prompt & Config Validation",
        "agent": "Supervisor Agent",
        "method": "Deterministic",
        "guidelines": [],
        "expected_tools": [],
    }
    saved = {
        "AV-G1-001": {
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
    out = braintrust_eval.publish(
        {"AV-G1-001": case},
        saved,
        bt=fake,
        experiment_name="test-exp",
    )
    assert fake.project == "loan-agents"
    assert fake.dataset_name == "loan-agent-test-cases-1"
    assert fake.dataset.rows[0]["id"] == "AV-G1-001"
    assert fake.eval_kwargs["experiment_name"] == "test-exp"
    assert out["experiment_url"].endswith("/experiments/t")
    assert out["grades"]["AV-G1-001"]["verdict"] == "PASS"
