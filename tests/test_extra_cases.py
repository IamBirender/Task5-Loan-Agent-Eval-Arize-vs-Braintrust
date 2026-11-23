import json
from collections import Counter

from scoring.cases import EXTRA, EXTRA_G21_G22, _case


def test_g9_g20_six_cases_each():
    doc = json.loads(EXTRA.read_text(encoding="utf-8"))
    loaded = [_case(j, None, j["description"], "added by us") for j in doc["testCases"]]
    assert len(loaded) == 72
    counts = Counter(c["gate_code"] for c in loaded)
    for gate in range(9, 21):
        assert counts[f"G{gate}"] == 6, (gate, counts)
    ids = [c["id"] for c in loaded]
    assert "AV-G9-X01" in ids
    assert "AV-G20-X01" in ids
    assert len(ids) == len(set(ids))


def test_g21_g22_hundred_each():
    doc = json.loads(EXTRA_G21_G22.read_text(encoding="utf-8"))
    loaded = [_case(j, None, j["description"], "added by us") for j in doc["testCases"]]
    assert len(loaded) == 200
    counts = Counter(c["gate_code"] for c in loaded)
    assert counts["G21"] == 100
    assert counts["G22"] == 100
    ids = [c["id"] for c in loaded]
    assert "AV-G21-X01" in ids
    assert "AV-G21-X100" in ids
    assert "AV-G22-X01" in ids
    assert "AV-G22-X100" in ids
    assert len(ids) == len(set(ids))
    assert all(c["agent"] == "Compliance Validation Agent" for c in loaded)
