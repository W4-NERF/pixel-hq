#!/usr/bin/env python3
"""Print WCAG contrast for both UI palettes; fail below text/accent thresholds.

Stdlib only. An optional CSS path supports offline palette regression fixtures;
without an argument the tool checks its own checkout, regardless of the cwd.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLORS = ("fg", "mut", "mut2", "olive", "rust", "amber", "green")
TEXT = {"fg", "mut", "mut2"}
SELECTORS = {":root": "dark", ':root[data-mode="light"]': "light"}


def luminance(color: str) -> float:
    """WCAG relative luminance of an opaque six-digit sRGB color."""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("expected an opaque six-digit hex color")
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))


def contrast(foreground: str, background: str) -> float:
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def parse_palettes(css: str) -> dict:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    blocks = re.findall(r'(:root(?:\[data-mode="light"\])?)\s*\{([^{}]*)\}', css)
    palettes = {}
    for selector, body in blocks:
        mode = SELECTORS[selector]
        if mode in palettes:
            raise ValueError("expected exactly one palette per mode")
        values = dict(re.findall(r"--([\w-]+)\s*:\s*([^;{}]+)", body))
        for name in ("bg", "card", *COLORS):
            if name not in values:
                raise ValueError(f"{mode}: missing --{name}")
            luminance(values[name].strip())
        palettes[mode] = {name: value.strip() for name, value in values.items()}
    if set(palettes) != {"dark", "light"}:
        raise ValueError("expected dark and light palette blocks")
    return {mode: palettes[mode] for mode in ("dark", "light")}


def main(path: Path = ROOT / "pixelhq/ui/style.css") -> int:
    try:
        palettes = parse_palettes(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        print("contrast: " + (str(error) if isinstance(error, ValueError) else type(error).__name__))
        return 1
    failed = False
    print(f"{'mode':<6} {'color':<9} {'--bg':>8} {'--card':>8} {'minimum':>8} result")
    for mode, values in palettes.items():
        for name in COLORS:
            minimum = 4.5 if name in TEXT else 3.0
            ratios = [contrast(values[name], values[background]) for background in ("bg", "card")]
            passed = all(ratio >= minimum for ratio in ratios)
            failed |= not passed
            print(f"{mode:<6} {'--' + name:<9} {ratios[0]:8.3f} {ratios[1]:8.3f} {minimum:8.1f} {'ok' if passed else 'FAIL'}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "pixelhq/ui/style.css"))
