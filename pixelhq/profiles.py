"""Read profile metadata directly from a Hermes home."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def _scalar(raw: str) -> str:
    if raw.strip().startswith("#"):
        return ""
    match = re.match(r'''("(?:\\.|[^"\\])*"|'(?:''|[^'])*'|.*?)(?:\s+#.*)?$''', raw.strip())
    value = match.group(1).strip() if match else raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return "" if value in ("null", "~") else value


def _fallback(text: str) -> dict:
    data, model_indent, child_indent = {}, None, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^(\s*)([\w-]+):\s*(.*)$", line)
        if not match:
            continue
        indent, key, raw = match.groups()
        if model_indent is not None and len(indent) <= model_indent:
            model_indent = None
        if not indent and key == "model" and not raw.split("#", 1)[0].strip():
            model_indent = 0
            child_indent = None
            data["model"] = {}
        elif not indent and key == "model":
            data["model"] = _scalar(raw)
        elif model_indent is not None:
            if child_indent is None:
                child_indent = len(indent)
            if len(indent) == child_indent and key in ("default", "provider"):
                data["model"][key] = _scalar(raw)
        elif not indent and key == "description":
            data[key] = _scalar(raw)
    return data


def _warn(warnings: list[str], source: str, error) -> None:
    warnings.append(f"{source}: {' '.join(str(error).split())}"[:120])


def _read(path: Path, warnings: list[str]) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as exc:
        _warn(warnings, f"{path.parent.name}/{path.name}", exc)
        return {}
    try:
        data = yaml.safe_load(text) if yaml is not None else _fallback(text)
        if data is not None and not isinstance(data, dict):
            raise ValueError("expected a mapping")
        return data or {}
    except Exception as exc:
        # Parser diagnostics may quote credentials from the source YAML.
        _warn(warnings, f"{path.parent.name}/{path.name}", f"invalid YAML ({type(exc).__name__})")
        return {}


def _gateway(directory: Path, warnings: list[str]) -> str | None:
    path = directory / "gateway.pid"
    try:
        text = path.read_text(encoding="utf-8").strip()
        data = json.loads(text) if text.startswith("{") else int(text)
        pid = data.get("pid") if isinstance(data, dict) else data
        if type(pid) is not int or pid <= 0:
            raise ValueError("invalid gateway PID")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        # The JSON may contain private argv entries; do not echo its contents or OS paths.
        _warn(warnings, f"{directory.name}/gateway.pid", f"invalid or unreadable PID ({type(exc).__name__})")
        return None
    try:
        os.kill(pid, 0)
    except PermissionError:
        return "running"
    except (OSError, ValueError, OverflowError):
        return "stopped"
    return "running"


def root_home() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
    return home.parent.parent if home.parent.name == "profiles" else home


def list_profiles(home: Path | None = None, warnings: list[str] | None = None) -> dict:
    warnings = warnings if warnings is not None else []
    root = Path(home) if home is not None else root_home()
    directories = {"default": root} if root.is_dir() else {}
    parent = root / "profiles"
    try:
        children = sorted(parent.iterdir()) if parent.is_dir() else []
    except OSError as exc:
        _warn(warnings, "profiles", exc)
        children = []
    for directory in children:
        if directory.name.startswith(("_", ".")):
            continue
        try:
            if directory.is_dir() and ((directory / "config.yaml").is_file() or (directory / "profile.yaml").is_file()):
                directories[directory.name] = directory
        except OSError as exc:
            _warn(warnings, f"profiles/{directory.name}", exc)
    out = {}
    for name, directory in directories.items():
        config = directory / "config.yaml"
        metadata = directory / "profile.yaml"
        cfg = _read(config, warnings)
        meta = _read(metadata, warnings)
        model = cfg.get("model") or {}
        if isinstance(model, str):
            model = {"default": model}
        if not isinstance(model, dict):
            _warn(warnings, f"{name}/config.yaml", "expected a model mapping or string")
            model = {}
        out[name] = {"model": str(model.get("default") or "?"), "provider": str(model.get("provider") or "?"),
                     "gateway": _gateway(directory, warnings),
                     "description": str(meta.get("description") or ""), "dir": directory}
    return out
