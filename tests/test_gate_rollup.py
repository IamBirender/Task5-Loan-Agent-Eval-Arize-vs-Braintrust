from scoring import runs


def test_g20_rollup_label_distinct():
    cases = [
        {"id": f"AV-G{n}-001", "gate": f"G{n} · x", "gate_code": f"G{n}"}
        for n in range(1, 20)
    ]
    graded = {c["id"]: {"verdict": "PASS"} for c in cases}
    table = runs.gate_table(graded, cases)
    labels = [r["gate"] for r in table]
    assert "G20 rollup · derived from G1–G19" in labels
    assert table[-1]["gate_verdict"] == "PASS"
