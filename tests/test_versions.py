"""Release metadata stays consistent: plugin.yaml, the dashboard manifest and the newest changelog entry."""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _released_versions() -> list[str]:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", changelog, flags=re.MULTILINE)


def test_plugin_and_dashboard_manifest_versions_match():
    plugin = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    dashboard = json.loads((ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))
    assert dashboard["name"] == plugin["name"]
    assert dashboard["version"] == plugin["version"]


def test_manifest_version_is_the_newest_changelog_release():
    plugin = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    released = _released_versions()
    assert released, "CHANGELOG.md has no released version"
    assert released[0] == plugin["version"]


def test_changelog_releases_are_listed_newest_first_without_duplicates():
    released = [tuple(int(part) for part in version.split(".")) for version in _released_versions()]
    assert released == sorted(set(released), reverse=True)
