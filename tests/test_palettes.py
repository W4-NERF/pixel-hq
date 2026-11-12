"""Palette ownership, exact specified colors and live sprite palette changes."""
import re
import subprocess
import sys
from pathlib import Path

from pixelhq import page
from tests.test_contrast import contrast_tool
from tests.test_review_ui import run_ui

ROOT = Path(__file__).resolve().parents[1]
DARK = {"bg": "#0B0F14", "bg2": "#10161E", "card": "#131B24", "card2": "#18222D",
        "fg": "#DCE4EC", "mut": "#7E8B99", "mut2": "#93A1AF", "olive": "#7E9A52",
        "rust": "#C1652E", "amber": "#C9A23F", "green": "#5FA36A"}
LIGHT = {"bg": "#F4F6F8", "bg2": "#E9EDF1", "card": "#FFFFFF", "card2": "#F0F3F6",
         "fg": "#17202A", "mut": "#5B6875", "mut2": "#46525E", "olive": "#5F7A3A",
         "rust": "#A8521F", "amber": "#8A6A12", "green": "#3F7F4B"}


def test_css_has_exactly_two_palettes_with_all_colors_behind_custom_properties():
    source = (ROOT / "pixelhq/ui/style.css").read_text(encoding="utf-8")
    blocks = list(re.finditer(r'(:root(?:\[data-mode="light"\])?)\s*\{[^{}]*\}', source))
    assert [match[1] for match in blocks] == [":root", ':root[data-mode="light"]']
    outside = source
    for block in reversed(blocks):
        outside = outside[:block.start()] + outside[block.end():]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\btransparent\b", outside)
    palettes = contrast_tool().parse_palettes(source)
    for mode, expected in (("dark", DARK), ("light", LIGHT)):
        assert {name: palettes[mode][name] for name in expected} == expected
    assert set(palettes["dark"]) - {"px"} == set(palettes["light"]) - {"px"}
    for block, line in zip(blocks, ("rgba(206,220,235,0.14)", "rgba(23,32,42,.16)"), strict=True):
        assert f"--line:{line}" in block[0]
    defined = set(palettes["dark"]) | {"side"}
    assert set(re.findall(r"var\(--([\w-]+)", outside)) <= defined


def test_javascript_hex_and_fixed_rgba_literals_live_in_one_palette_constant():
    source = page.bundle_js()
    blocks = list(re.finditer(r"const PALETTE\s*=\s*\{.*?\n\};", source, flags=re.S))
    assert len(blocks) == 1
    block = blocks[0]
    outside = source[:block.start()] + source[block.end():]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", outside)
    assert "dark:" in block[0] and "light:" in block[0]


def test_sprite_colors_change_on_host_theme_without_changing_roster_color(tmp_path):
    run_ui(tmp_path, """
const onMsg=listeners.get('message'), bot={...DATA.bots[0],color:'#5B7A99',leader:true};
onMsg({source:window.parent,data:{pixelhq:DATA}});
const dark=sprite(bot,4); assert.equal(safeColor(null),PALETTE.dark.fallback);
onMsg({source:window.parent,data:{pixelhqTheme:{mode:'light'}}});
const light=sprite(bot,4);
assert.notEqual(light,dark);
assert.ok(dark.includes(PALETTE.dark.amber)); assert.ok(light.includes(PALETTE.light.amber));
assert.ok(dark.includes(PALETTE.dark.eye)); assert.ok(light.includes(PALETTE.light.eye));
assert.ok(dark.includes(bot.color)&&light.includes(bot.color));
assert.equal(safeColor('not a color'),PALETTE.light.fallback);
assert.equal(safeColor('#5B7A99'),'#5B7A99');
for(const id of ['detail','tb','blist','lactive']){
  const html=elements.get(id).innerHTML;
  assert.ok(!html.includes(PALETTE.dark.eye),id+' must not retain old sprite pixels');
}
DATA.cfg.appearance='dark';onMsg({source:window.parent,data:{pixelhq:DATA}});
assert.equal(sprite(bot,4),dark);
""", iframe=True)


def test_shipped_palettes_pass_the_standalone_stdlib_gate_from_another_cwd(tmp_path):
    result = subprocess.run([sys.executable, "-S", str(ROOT / "tools/contrast.py")], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL" not in result.stdout
    assert len([line for line in result.stdout.splitlines() if line.startswith(("dark ", "light "))]) == 14
