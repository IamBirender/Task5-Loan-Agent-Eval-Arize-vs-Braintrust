from pathlib import Path

from scripts.package_agent_code import bundle_into


def test_bundle_without_deps_writes_entrypoint_and_prompts(tmp_path: Path):
    dest = bundle_into(tmp_path / "agent_code", install_deps=False)
    assert (dest / "main.py").is_file()
    assert "loan_agents.runtime" in (dest / "main.py").read_text(encoding="utf-8")
    assert (dest / "loan_agents" / "runtime.py").is_file()
    assert (dest / "loan_agents" / "prompts" / "pool_screening.txt").is_file()
    assert not (dest / "loan_agents" / "data.py").exists()
    assert (dest / ".bundle_stamp").is_file()


def test_bundle_without_deps_is_cached(tmp_path: Path):
    dest = tmp_path / "agent_code"
    first = bundle_into(dest, install_deps=False)
    stamp = (first / ".bundle_stamp").read_text(encoding="utf-8")
    (first / "main.py").write_text("mutated", encoding="utf-8")
    second = bundle_into(dest, install_deps=False)
    assert (second / "main.py").read_text(encoding="utf-8") == "mutated"
    assert (second / ".bundle_stamp").read_text(encoding="utf-8") == stamp
