import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", *args], cwd=ROOT, capture_output=True, text=True)


def test_ruff_check_passes() -> None:
    result = _run("ruff", "check", "src", "tests")
    assert result.returncode == 0, result.stdout + result.stderr


def test_ruff_format_is_clean() -> None:
    result = _run("ruff", "format", "--check", "src", "tests")
    assert result.returncode == 0, result.stdout + result.stderr


def test_ty_passes() -> None:
    result = subprocess.run(
        ["uv", "run", "ty", "check", "src", "tests"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_literal_no_break_spaces_in_source_or_tests() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for folder in ("src", "tests")
        for path in sorted((ROOT / folder).rglob("*.py"))
        if any(char in path.read_text(encoding="utf-8") for char in ("\xa0", "\u202f"))
    ]
    assert offenders == []
