"""Keep the UI compatible with an opaque-origin, scripts-only Desktop frame."""
import re
from pathlib import Path

import pytest

from pixelhq import page

ROOT = Path(__file__).resolve().parents[1]
UI_SOURCES = {
    "pixelhq/ui/js (bundle)": page.bundle_js,
    "pixelhq/ui/index.html": lambda: (ROOT / "pixelhq/ui/index.html").read_text(encoding="utf-8"),
}
COMMENTS = re.compile(
    r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|'''
    r"/\*.*?\*/|//[^\r\n]*|<!--.*?-->",
    re.DOTALL,
)
FORBIDDEN = {
    "form element": r"<\s*form\b",
    "submit button": r'''\btype\s*=\s*(?:"submit"|'submit'|submit(?=[\s>]))''',
    "submit handler": r"\bonsubmit\b",
    "requestSubmit": r"\brequestSubmit\b",
    "submit method": r"\.\s*submit\s*\(",
    "localStorage": r"\blocalStorage\b",
    "sessionStorage": r"\bsessionStorage\b",
    "document.cookie": r"\bdocument\s*\.\s*cookie\b",
    "window.open": r"\bwindow\s*\.\s*open\b",
    "colour picker": r'''<\s*input\b[^>]*\btype\s*=\s*(?:"color"|'color'|color(?=[\s>]))''',
    "file picker": r'''<\s*input\b[^>]*\btype\s*=\s*(?:"file"|'file'|file(?=[\s>]))''',
    "download attribute": r"(?<![\w-])download\s*=",
    "global dialog": (
        r"(?<![\w$.-])(?:(?:window|globalThis|self)\.)?(?:alert|confirm|prompt)\s*\("
        r"(?![^()]*\)\s*\{)"
    ),
}


def strip_comments(source):
    """Preserve quoted markup and URLs while removing JS/HTML comments."""
    return COMMENTS.sub(lambda match: match.group(1) if match.group(1) is not None else " ", source)


def sandbox_violations(source):
    source = strip_comments(source)
    # A spaced property access is still a method, not a bare global call.
    compact_dots = re.sub(r"\s*\.\s*", ".", source)
    return [name for name, pattern in FORBIDDEN.items()
            if re.search(pattern, compact_dots if name == "global dialog" else source, re.IGNORECASE)]


@pytest.mark.parametrize("name", UI_SOURCES)
def test_ui_respects_scripts_only_sandbox(name):
    violations = sandbox_violations(UI_SOURCES[name]())
    assert violations == [], f"{name}: forbidden sandbox features: {', '.join(violations)}"


@pytest.mark.parametrize("path", sorted((ROOT / "pixelhq/ui/js").glob("*.js")), ids=lambda p: p.name)
def test_each_ui_script_file_respects_the_sandbox_on_its_own(path):
    assert sandbox_violations(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("name, source", [
    ("form element", '<form data-review-form>'),
    ("form element", '<FORM>'),
    ("submit button", '<button type="submit">'),
    ("submit button", "<button TYPE = 'submit'>"),
    ("submit button", '<button type=submit>'),
    ("submit handler", 'element.onsubmit = handler'),
    ("requestSubmit", 'element.requestSubmit()'),
    ("submit method", 'element . submit ()'),
    ("localStorage", 'localStorage.getItem("sample")'),
    ("sessionStorage", 'window.sessionStorage'),
    ("document.cookie", 'document . cookie = "sample=value"'),
    ("window.open", 'window . open("sample")'),
    ("colour picker", '<input type="color">'),
    ("colour picker", "<INPUT data-swatch TYPE = 'color'>"),
    ("file picker", '<input id="sample" type="file">'),
    ("file picker", '<input type=file>'),
    ("download attribute", '<a download="sample.json">'),
    ("download attribute", '<a DOWNLOAD = "sample.json">'),
    ("global dialog", 'alert("sample")'),
    ("global dialog", 'confirm ("sample")'),
    ("global dialog", 'prompt("sample")'),
    ("global dialog", 'window . confirm("sample")'),
    ("global dialog", 'globalThis.alert("sample")'),
    ("global dialog", 'self.prompt("sample")'),
    ("global dialog", 'if (confirm("sample")) { run(); }'),
])
def test_contract_detects_forbidden_features(name, source):
    assert name in sandbox_violations(source)


@pytest.mark.parametrize("source", [
    '<div data-review-form><button type="button" data-review-confirm>Confirm</button></div>',
    'const confirmButton = document.querySelector("[data-review-confirm]")',
    'const requestConfirmation = () => true; requestConfirmation()',
    'review_confirm()',
    '$confirm()',
    'data-review-confirm()',
    'dialog.alert("sample"); dialog.confirm("sample"); dialog.prompt("sample")',
    'dialog . confirm ("sample")',
    'dialog.window.confirm("sample")',
    'const dialog = {confirm() { return true; }, prompt(value) { return value; }}',
    'class Dialog { alert(value) { return value; } }',
    'function confirm(value) { return value; }',
])
def test_contract_allows_plain_controls_and_non_global_dialog_names(source):
    assert sandbox_violations(source) == []


@pytest.mark.parametrize("wrapper", ['/* {} */', '// {}\n', '<!-- {} -->'])
@pytest.mark.parametrize("name, source", [
    (name, source) for name, source in (
        ("form", '<form type="submit">'),
        ("handler", 'element.onsubmit = () => element.requestSubmit()'),
        ("method", 'element.submit()'),
        ("storage", 'localStorage; sessionStorage; document.cookie'),
        ("dialogs", 'alert(); confirm(); prompt(); window.open()'),
        ("pickers", '<input type="color"><input type="file"><a download="sample">'),
    )
])
def test_contract_ignores_comments(wrapper, name, source):
    assert sandbox_violations(wrapper.format(source)) == []


@pytest.mark.parametrize("source", [
    "const markup = '<form data-review-form>';",
    'const url = "https://example.invalid/sample"; alert("sample");',
    'const text = "/* not a comment */"; confirm("sample");',
    'const markup = `<input type="color">`;',
    '/* sample comment */ prompt("sample"); // another comment',
])
def test_comment_stripping_keeps_executable_code_and_quoted_markup(source):
    assert sandbox_violations(source)
