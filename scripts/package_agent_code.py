"""Build the AgentCore direct-code folder (Linux arm64 wheels, no Docker/ECR).

The four specialist runtimes share this package. AgentCore extracts it under
``/var/task`` and runs ``main.py``. Native wheels must be manylinux aarch64
because the runtime is ARM64 even when you synth on x86 EC2 or Windows.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO_ROOT / "infra" / "agent_image" / "requirements.txt"
MAIN_PY = REPO_ROOT / "infra" / "agent_image" / "main.py"
LOAN_AGENTS = REPO_ROOT / "loan_agents"
DEFAULT_OUTPUT = REPO_ROOT / "build" / "agent_code"
STAMP_NAME = ".bundle_stamp"
MAX_UNZIPPED_BYTES = 700 * 1024 * 1024
SKIP_LOAN_AGENT_FILES = frozenset({"data.py"})


class PackageError(RuntimeError):
    """Raised when the AgentCore zip contents cannot be produced."""


def _hash_sources() -> str:
    digest = hashlib.sha256()
    for path in (REQUIREMENTS, MAIN_PY):
        digest.update(path.read_bytes())
        digest.update(b"\0")
    for file_path in sorted(LOAN_AGENTS.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix in {".pyc"} or "__pycache__" in file_path.parts:
            continue
        digest.update(file_path.relative_to(REPO_ROOT).as_posix().encode())
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    digest.update(sys.version.encode())
    return digest.hexdigest()


def _copy_loan_agents(output_dir: Path) -> None:
    dest = output_dir / "loan_agents"
    if dest.exists():
        shutil.rmtree(dest)

    def ignore(directory: str, names: list[str]) -> set[str]:
        dropped = {n for n in names if n == "__pycache__" or n.endswith(".pyc")}
        if Path(directory).resolve() == LOAN_AGENTS.resolve():
            dropped.update(n for n in names if n in SKIP_LOAN_AGENT_FILES)
        return dropped

    shutil.copytree(LOAN_AGENTS, dest, ignore=ignore)
    shutil.copy2(MAIN_PY, output_dir / "main.py")


def _uv_install_cmd(output_dir: Path) -> list[str] | None:
    uv_bin = shutil.which("uv")
    if uv_bin:
        launcher = [uv_bin]
    else:
        launcher = [sys.executable, "-m", "uv"]
        probe = subprocess.run(
            [*launcher, "--version"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            return None
    return [
        *launcher,
        "pip",
        "install",
        "--python-platform",
        "aarch64-manylinux2014",
        "--python-version",
        "3.12",
        "--only-binary",
        ":all:",
        "--target",
        str(output_dir),
        "-r",
        str(REQUIREMENTS),
    ]


def _pip_install_cmd(output_dir: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--python-version",
        "3.12",
        "--platform",
        "manylinux2014_aarch64",
        "--implementation",
        "cp",
        "--abi",
        "cp312",
        "--only-binary",
        ":all:",
        "--upgrade",
        "--no-compile",
        "-r",
        str(REQUIREMENTS),
        "-t",
        str(output_dir),
    ]


def _pip_install(output_dir: Path) -> None:
    if not REQUIREMENTS.is_file():
        raise PackageError(f"missing {REQUIREMENTS}")
    commands = [cmd for cmd in (_uv_install_cmd(output_dir), _pip_install_cmd(output_dir)) if cmd]
    errors: list[str] = []
    for cmd in commands:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        if result.returncode == 0:
            return
        errors.append(f"{' '.join(cmd)}\n{result.stderr or result.stdout}")
    hint = (
        "On Windows, pip still applies win32 markers (mcp wants pywin32). "
        "Install uv (`pip install uv`) and retry, or package on Amazon Linux EC2."
        if sys.platform == "win32"
        else "Upgrade pip (`python -m pip install -U pip`) and retry."
    )
    raise PackageError(
        "Failed to install Linux arm64 wheels for AgentCore direct-code deploy. "
        f"{hint}\n" + "\n".join(errors[-1:])
    )


def _dir_size(path: Path) -> int:
    total = 0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            total += file_path.stat().st_size
    return total


def bundle_into(output_dir: Path | None = None, *, install_deps: bool = True) -> Path:
    """Populate ``output_dir`` with main.py, loan_agents, and (by default) deps."""
    if not LOAN_AGENTS.is_dir():
        raise PackageError(f"missing {LOAN_AGENTS}")
    if not MAIN_PY.is_file():
        raise PackageError(f"missing {MAIN_PY}")

    dest = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT
    dest.mkdir(parents=True, exist_ok=True)
    stamp = dest / STAMP_NAME
    source_hash = _hash_sources() + f"|deps={int(install_deps)}"
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == source_hash:
        return dest

    for child in dest.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    if install_deps:
        _pip_install(dest)
    _copy_loan_agents(dest)
    stamp.write_text(source_hash, encoding="utf-8")

    size = _dir_size(dest)
    if size > MAX_UNZIPPED_BYTES:
        raise PackageError(
            f"AgentCore package is {size} bytes unzipped; limit is {MAX_UNZIPPED_BYTES}"
        )
    return dest


def main() -> int:
    install = os.getenv("LOAN_AGENT_SKIP_DEPS", "").strip() not in {"1", "true", "yes"}
    target = bundle_into(install_deps=install)
    print(f"AgentCore code package: {target} ({_dir_size(target)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
