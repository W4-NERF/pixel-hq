"""WCAG math, strict palette parsing and the standalone stdlib contrast gate."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/contrast.py"
COLORS = ["fg", "mut", "mut2", "olive", "rust", "amber", "green"]


def contrast_tool():
    assert TOOL.is_file(), "The stdlib contrast gate must exist"
    spec = importlib.util.spec_from_file_location("contrast_gate", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_css(color="#FFFFFF", background="#000000"):
    props = f"--bg:{background};--card:{background};" + "".join(f"--{name}:{color};" for name in COLORS)
    return ':root{' + props + '}\n:root[data-mode="light"]{' + props + '}'


def test_wcag_reference_ratios_and_srgb_transfer():
    tool = contrast_tool()
    assert tool.luminance("#000000") == 0
    assert tool.luminance("#FFFFFF") == 1
    assert tool.contrast("#000000", "#FFFFFF") == 21
    assert tool.contrast("#FFFFFF", "#000000") == 21
    assert tool.contrast("#123456", "#123456") == 1
    assert tool.contrast("#777777", "#FFFFFF") == pytest.approx(4.478089, abs=0.000001)
    assert tool.luminance("#0A0A0A") == pytest.approx(0.00303527, abs=0.00000001)
    assert tool.luminance("#0B0B0B") == pytest.approx(0.00334654, abs=0.00000001)


@pytest.mark.parametrize("invalid", ["", "#FFF", "#GGGGGG", "rgba(0,0,0,1)", "var(--fg)"])
def test_unparseable_colors_are_not_silently_accepted(invalid):
    with pytest.raises(ValueError):
        contrast_tool().luminance(invalid)


@pytest.mark.parametrize("css", [
    "", ':root{--bg:#000000}', fixture_css().replace("--mut2:", "--missing:"),
    fixture_css() + '\n:root[data-mode="light"]{}',
])
def test_parser_rejects_missing_or_duplicate_palettes_and_required_colors(css):
    with pytest.raises(ValueError):
        contrast_tool().parse_palettes(css)


def test_parse_both_palettes_with_whitespace_and_comments():
    palettes = contrast_tool().parse_palettes("/* palette */\n" + fixture_css().replace(";", ";\n "))
    assert list(palettes) == ["dark", "light"]
    assert set(palettes["dark"]) == {"bg", "card", *COLORS}
    assert palettes["light"]["fg"] == "#FFFFFF"


@pytest.mark.parametrize("color,background,exit_code", [
    ("#FFFFFF", "#000000", 0), ("#000000", "#000000", 1),
    ("#777777", "#FFFFFF", 1),
])
def test_cli_gates_unrounded_ratios_and_prints_both_background_columns(tmp_path, color, background, exit_code):
    assert TOOL.is_file(), "The stdlib contrast gate must exist"
    css = tmp_path / "palette.css"
    css.write_text(fixture_css(color, background), encoding="utf-8")
    result = subprocess.run([sys.executable, "-S", str(TOOL), str(css)], capture_output=True, text=True, timeout=20)
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert "--bg" in result.stdout and "--card" in result.stdout and "minimum" in result.stdout
    rows = [line.split() for line in result.stdout.splitlines() if line.startswith(("dark ", "light "))]
    assert len(rows) == 14
    for mode in ("dark", "light"):
        assert [row[1] for row in rows if row[0] == mode] == ["--" + name for name in COLORS]
    assert ("FAIL" in result.stdout) is bool(exit_code)
