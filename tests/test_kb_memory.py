from loan_agents.aws_kb import normalize_passage
from loan_agents.aws_memory import _record_to_dict


def test_normalize_kb_passage():
    raw = {
        "content": {"text": "Current Actual UPB is the unpaid principal balance."},
        "location": {"s3Location": {"uri": "s3://loan-docs/crt-file-layout-and-glossary.pdf"}},
        "metadata": {"page": 3},
        "score": 0.91,
    }
    out = normalize_passage(raw)
    assert out["source"] == "crt-file-layout-and-glossary.pdf"
    assert out["page"] == 3
    assert "unpaid principal" in out["text"]
    assert out["score"] == 0.91


def test_memory_record_normalizes_nested_content():
    raw = {
        "memoryRecordId": "abc",
        "namespace": "credit_events",
        "content": {"text": "{\"loan_identifier\": \"100352555665\"}"},
        "score": 0.2,
    }
    out = _record_to_dict(raw)
    assert out["id"] == "abc"
    assert out["namespace"] == "credit_events"
    assert "100352555665" in out["content"]
