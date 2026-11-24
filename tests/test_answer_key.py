from step2_check_answer_key import audit
from scoring.cases import load


def test_extras_have_no_unreproducible_figures():
    report = audit(load())
    assert report["n"] == 2500
    assert report["n_senior"] == 60
    assert report["n_extras"] == 2440
    assert report["extra_missing"] == []
    assert report["format"] == []
    assert report["tools"] == []
    assert {c["id"] for c, _ in report["senior_missing"]} <= {"AV-G2-005", "AV-G21-003"}
