import json
from collections import Counter
from pathlib import Path

from scoring.cases import EXTRA, _case


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
