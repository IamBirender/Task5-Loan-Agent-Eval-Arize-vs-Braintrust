import pytest

from scripts import check_aws_ready as ready


class _Sts:
    def get_caller_identity(self):
        return {"Account": "123", "Arn": "arn:aws:iam::123:role/LoanEvalRunner"}


class _BedrockOk:
    def list_foundation_models(self):
        return {"modelSummaries": [{"modelId": m} for m in ready.REQUIRED_MODELS]}


class _BedrockMissing:
    def list_foundation_models(self):
        return {"modelSummaries": [{"modelId": "amazon.titan-embed-text-v2:0"}]}


class _SsmMissing:
    def get_parameter(self, Name):
        raise RuntimeError("not found")


def test_region_ok():
    assert ready.check_region("us-east-1") == "us-east-1"


def test_missing_model_raises():
    with pytest.raises(ready.ReadyError):
        ready.check_bedrock_models(_BedrockMissing())


def test_granted_models():
    assert ready.check_bedrock_models(_BedrockOk()) == list(ready.REQUIRED_MODELS)


def test_missing_runtime_arn_raises():
    with pytest.raises(ready.ReadyError):
        ready.check_runtime_arns(_SsmMissing())


def test_identity():
    ident = ready.check_identity(_Sts())
    assert "LoanEvalRunner" in ident["arn"]
