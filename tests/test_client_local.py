from loan_agents import client, models
from loan_agents.aws_config import LoanConfig


def test_invoke_mode_local(monkeypatch):
    monkeypatch.setenv("LOAN_AGENTCORE_INVOKE", "local")
    assert client.invoke_mode("arn:aws:bedrock-agentcore:us-east-1:1:runtime/x") == "local"


def test_invoke_mode_runtime(monkeypatch):
    monkeypatch.setenv("LOAN_AGENTCORE_INVOKE", "runtime")
    assert client.invoke_mode(None) == "runtime"


def test_local_specialist_dryrun(monkeypatch):
    monkeypatch.setenv("LOAN_AGENTCORE_INVOKE", "local")
    monkeypatch.delenv("LOAN_AURORA_CLUSTER_ARN", raising=False)
    monkeypatch.delenv("LOAN_AURORA_SECRET_ARN", raising=False)
    monkeypatch.setattr(
        client.aws_config,
        "load_config",
        lambda ssm_client=None: LoanConfig(region="us-east-1"),
    )
    models.PROVIDER = "dryrun"
    out = client.invoke_specialist(
        "pool_screening",
        "Run the default risk screen.",
        "sess-local-agentcore-host-33charsxx",
        payload={"case_id": "AV-G1-001"},
    )
    assert "dry run" in out["answer"]
    assert out["agent"] == "pool_screening"
    assert len(out["session_id"]) >= 33
