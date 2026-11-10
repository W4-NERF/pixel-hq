"""The function-size gate checks Python syntax spans without importing application code."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/funclen.py"


def test_funclen_reports_only_oversized_functions_in_the_two_source_trees(tmp_path):
    for directory in ("pixelhq/nested", "dashboard", "tests"):
        (tmp_path / directory).mkdir(parents=True)
    # Count from def through the last statement, including blank/comment lines.
    (tmp_path / "pixelhq/nested/sample.py").write_text(
        "@decorator\nasync def lengthy():\n" + "    # Padding\n\n" * 39 + "    pass\n    pass\n",
        encoding="utf-8")
    (tmp_path / "dashboard/sample.py").write_text(
        "class Sample:\n    def at_limit(self):\n" + "        pass\n" * 79 +
        "\ndef outer():\n    async def inner():\n" + "        pass\n" * 80 + "    return inner\n",
        encoding="utf-8")
    (tmp_path / "tests/ignored.py").write_text("def ignored():\n" + "    pass\n" * 100, encoding="utf-8")
    result = subprocess.run([sys.executable, str(TOOL), str(tmp_path)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert "pixelhq/nested/sample.py:2: lengthy: 81 lines" in lines
    assert "dashboard/sample.py:83: outer: 83 lines" in lines
    assert "dashboard/sample.py:84: inner: 81 lines" in lines
    assert len(lines) == 3


def test_funclen_is_quiet_when_functions_fit_the_limit(tmp_path):
    (tmp_path / "pixelhq").mkdir()
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "pixelhq/sample.py").write_text(
        "def at_limit():\n" + "    pass\n" * 79, encoding="utf-8")
    result = subprocess.run([sys.executable, str(TOOL), str(tmp_path)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == result.stderr == ""


def test_repository_functions_fit_the_limit_even_from_another_working_directory(tmp_path):
    result = subprocess.run([sys.executable, str(TOOL)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == result.stderr == ""
