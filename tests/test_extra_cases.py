import json
import re
from collections import Counter

from scoring.cases import EXTRA, _case, load
from scripts.build_extra_test_cases import GATES, SENIOR_EXPECTED_CAP, MAX_GUIDELINES

ID_RE = re.compile(r"^AV-G(\d+)-X(\d{2,3})$")
ALLOWED_METHODS = {"Deterministic", "LLM-as-judge", "Human review", "Metric"}
META_KEYS = {"testId", "qualityGate", "phase", "evaluationMethod", "source", "fault", "limits"}


def test_extra_json_hundred_unique_per_gate():
    doc = json.loads(EXTRA.read_text(encoding="utf-8"))
    loaded = [_case(j, None, j["description"], "added by us") for j in doc["testCases"]]
    assert len(loaded) == 2440
    counts = Counter(c["gate_code"] for c in loaded)
    for gate in range(1, 21):
        assert counts[f"G{gate}"] == 111, (gate, counts[f"G{gate}"])
    assert counts["G21"] == 110
    assert counts["G22"] == 110
    ids = [c["id"] for c in loaded]
    assert len(ids) == len(set(ids))
    assert "AV-G1-X01" in ids
    assert "AV-G1-X111" in ids
    assert "AV-G22-X110" in ids
    prompts = [(c["gate_code"], c["input"].strip().lower()) for c in loaded]
    assert len(prompts) == len(set(prompts))


def test_all_loaded_ids_unique_and_count():
    cases = load()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    assert len(cases) == 2500
    counts = Counter(c["gate_code"] for c in cases)
    for gate in range(1, 9):
        assert counts[f"G{gate}"] == 117, (gate, counts[f"G{gate}"])
    for gate in range(9, 21):
        assert counts[f"G{gate}"] == 111, (gate, counts[f"G{gate}"])
    assert counts["G21"] == 116
    assert counts["G22"] == 116


def test_extras_do_not_require_unreproducible_peer_distances():
    doc = json.loads(EXTRA.read_text(encoding="utf-8"))
    blob = json.dumps(doc["testCases"])
    assert "0.075" not in blob
    assert "0.286" not in blob
    assert "0.377" not in blob
    assert "5 PASS, 2 WARN, 3 NOTE" not in blob


def test_extra_expected_matches_senior_format():
    doc = json.loads(EXTRA.read_text(encoding="utf-8"))
    lens = []
    for j in doc["testCases"]:
        exp = j["expectations"]["expectedResponse"]["Response"]
        gl = j["expectations"].get("guidelines") or []
        assert exp.startswith("The response must"), j["name"]
        assert len(exp) <= SENIOR_EXPECTED_CAP, (j["name"], len(exp))
        assert len(gl) <= MAX_GUIDELINES, (j["name"], gl)
        lens.append(len(exp))
    assert max(lens) <= SENIOR_EXPECTED_CAP
    assert sum(lens) / len(lens) < 280


def test_extra_metadata_matches_gate_and_ids_are_unique():
    doc = json.loads(EXTRA.read_text(encoding="utf-8"))
    names, test_ids = [], []
    for j in doc["testCases"]:
        name = j["name"]
        meta = j["metadata"]
        names.append(name)
        test_ids.append(meta["testId"])
        match = ID_RE.match(name)
        assert match, name
        gate = int(match.group(1))
        quality_gate, phase = GATES[gate]
        assert meta["testId"] == name
        assert meta["qualityGate"] == quality_gate, (name, meta["qualityGate"])
        assert meta["phase"] == phase, (name, meta["phase"])
        assert meta["evaluationMethod"] in ALLOWED_METHODS, (name, meta["evaluationMethod"])
        assert meta["source"] == "added by us"
        assert set(meta) <= META_KEYS, (name, set(meta) - META_KEYS)
        assert "Fannie Mae" not in json.dumps(meta)
    assert len(names) == len(set(names)) == 2440
    assert len(test_ids) == len(set(test_ids)) == 2440
    loaded = load()
    loaded_ids = [c["id"] for c in loaded]
    assert len(loaded_ids) == len(set(loaded_ids)) == 2500
