#!/usr/bin/env python3
"""Line and function length gate for the plain-JS sources (stdlib only, no JS parser needed).

Checked files: ``pixelhq/ui/js/*.js`` and ``desktop/plugin.js``.

* A line may have at most 140 characters; a longer line is only accepted when it ends with ``/* table */``
  (pure data tables such as sprite bitmaps or palettes).
* A function (declaration, function expression, method or arrow function with a block body) may span at most
  80 lines, counted from the line of its head to the line of its closing brace. Nested functions count on their own.
  Arrow functions with an expression body have no braces and are covered by the line limit only.

Exit 1 with ``path:line: message`` for every violation, otherwise 0. The last line states what was measured.
An optional root path supports offline fixture checks; the default is the repository containing this tool.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_LINE = 140
MAX_FUNCTION = 80
TABLE_MARK = "/* table */"
CONTROL = {"if", "for", "while", "switch", "catch", "with"}
# After these words a "/" starts a regular expression, after any other identifier it is a division.
REGEX_AFTER_WORD = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else",
                    "yield", "await"}
PUNCT3 = (">>>=", "...", "===", "!==", "**=", "<<=", ">>=", ">>>", "&&=", "||=", "??=")
PUNCT2 = ("=>", "==", "!=", "<=", ">=", "&&", "||", "??", "?.", "++", "--", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
          "<<", ">>", "**")


class Scanner:
    """Turns JS text into (kind, text, line) tokens: id, num, str, regex, punct. Comments are skipped."""

    def __init__(self, text: str):
        self.text, self.i, self.line = text, 0, 1
        self.tokens: list[tuple[str, str, int]] = []
        self.braces: list[str] = []  # "code" for ordinary braces, "tmpl" for the "${" of a template literal

    def peek(self, k: int = 0) -> str:
        j = self.i + k
        return self.text[j] if j < len(self.text) else ""

    def advance(self, n: int = 1) -> str:
        chunk = self.text[self.i:self.i + n]
        self.line += chunk.count("\n")
        self.i += n
        return chunk

    def emit(self, kind: str, text: str, line: int) -> None:
        self.tokens.append((kind, text, line))

    def regex_allowed(self) -> bool:
        if not self.tokens:
            return True
        kind, text, _ = self.tokens[-1]
        if kind in ("num", "str", "regex"):
            return False
        if kind == "id":
            return text in REGEX_AFTER_WORD
        return text not in (")", "]", "}")

    def skip_comment(self) -> bool:
        if self.peek() == "/" and self.peek(1) == "/":
            while self.peek() and self.peek() != "\n":
                self.advance()
            return True
        if self.peek() == "/" and self.peek(1) == "*":
            end = self.text.find("*/", self.i + 2)
            self.advance((len(self.text) if end < 0 else end + 2) - self.i)
            return True
        return False

    def read_quoted(self, quote: str) -> None:
        line = self.line
        self.advance()
        while self.peek() and self.peek() != quote:
            self.advance(2 if self.peek() == "\\" else 1)
        self.advance()
        self.emit("str", quote, line)

    def read_template(self) -> None:
        """Scan template text up to the closing backtick or the next ``${`` (which switches back to code)."""
        line = self.line
        while self.peek():
            ch = self.peek()
            if ch == "\\":
                self.advance(2)
            elif ch == "`":
                self.advance()
                break
            elif ch == "$" and self.peek(1) == "{":
                self.advance(2)
                self.braces.append("tmpl")
                break
            else:
                self.advance()
        self.emit("str", "`", line)

    def read_regex(self) -> None:
        line = self.line
        self.advance()
        in_class = False
        while self.peek() and (in_class or self.peek() != "/") and self.peek() != "\n":
            ch = self.peek()
            if ch == "\\":
                self.advance(2)
                continue
            in_class = (in_class and ch != "]") or ch == "["
            self.advance()
        self.advance()
        while self.peek().isalpha():
            self.advance()
        self.emit("regex", "/", line)

    def read_word(self) -> None:
        start, line = self.i, self.line
        while self.peek() and (self.peek().isalnum() or self.peek() in "_$"):
            self.advance()
        word = self.text[start:self.i]
        self.emit("num" if word[0].isdigit() else "id", word, line)

    def read_punct(self) -> None:
        line = self.line
        for group in (PUNCT3, PUNCT2):
            for op in group:
                if self.text.startswith(op, self.i):
                    self.advance(len(op))
                    self.emit("punct", op, line)
                    return
        ch = self.advance()
        if ch == "{":
            self.braces.append("code")
        elif ch == "}" and self.braces and self.braces.pop() == "tmpl":
            self.read_template()
            return
        self.emit("punct", ch, line)

    def run(self) -> list[tuple[str, str, int]]:
        while self.i < len(self.text):
            ch = self.peek()
            if ch.isspace():
                self.advance()
            elif self.skip_comment():
                continue
            elif ch in "'\"":
                self.read_quoted(ch)
            elif ch == "`":
                self.advance()
                self.read_template()
            elif ch == "/" and self.regex_allowed():
                self.read_regex()
            elif ch.isalnum() or ch in "_$":
                self.read_word()
            else:
                self.read_punct()
        return self.tokens


def head_start(tokens: list, index: int) -> int:
    """Index of the first token of a function head, including a leading ``async``."""
    if index > 0 and tokens[index - 1][1] == "async":
        return index - 1
    return index


def function_head(tokens: list, pairs: dict, brace: int):
    """For the ``{`` at ``brace``: (head token index, name) when it opens a function body, else None."""
    prev = brace - 1
    if prev < 0:
        return None
    if tokens[prev][1] == "=>":
        before = prev - 1
        if tokens[before][1] == ")":
            before = pairs[before]
        return head_start(tokens, before), "(arrow)"
    if tokens[prev][1] != ")" or prev not in pairs:
        return None
    open_at = pairs[prev]
    before = open_at - 1
    if before >= 0 and tokens[before][1] == "*":
        before -= 1
    if before < 0 or tokens[before][0] != "id" or tokens[before][1] in CONTROL:
        return None
    name = tokens[before][1]
    if name == "function":
        return head_start(tokens, before), "(anonymous)"
    if before > 0 and tokens[before - 1][1] == "function":
        return head_start(tokens, before - 1), name
    return head_start(tokens, before), name


def match_parens(tokens: list) -> dict:
    pairs, stack = {}, []
    for index, (_, text, _) in enumerate(tokens):
        if text == "(":
            stack.append(index)
        elif text == ")" and stack:
            pairs[index] = stack.pop()
    return pairs


def functions(tokens: list):
    """Yield (start line, end line, name) for every function with a block body."""
    pairs, stack = match_parens(tokens), []
    for index, (kind, text, line) in enumerate(tokens):
        if kind != "punct" or text not in ("{", "}"):
            continue
        if text == "{":
            head = function_head(tokens, pairs, index)
            stack.append((tokens[head[0]][2], head[1]) if head else None)
        elif stack:
            entry = stack.pop()
            if entry:
                yield entry[0], line, entry[1]


def check_file(path: Path, rel: str, stats: dict) -> list[str]:
    problems = []
    text = path.read_text(encoding="utf-8")
    for number, raw in enumerate(text.splitlines(), 1):
        length = len(raw)
        if not raw.rstrip().endswith(TABLE_MARK) and length > stats["line"][0]:
            stats["line"] = (length, f"{rel}:{number}")
        if length > MAX_LINE and not raw.rstrip().endswith(TABLE_MARK):
            problems.append(f"{rel}:{number}: line has {length} characters (limit {MAX_LINE}; data tables end with {TABLE_MARK})")
    for start, end, name in sorted(functions(Scanner(text).run())):
        size = end - start + 1
        if size > stats["function"][0]:
            stats["function"] = (size, f"{rel}:{start} {name}")
        if size > MAX_FUNCTION:
            problems.append(f"{rel}:{start}: function {name} has {size} lines (limit {MAX_FUNCTION})")
    return problems


def sources(root: Path) -> list[Path]:
    files = sorted((root / "pixelhq" / "ui" / "js").glob("*.js"), key=lambda p: p.name)
    plugin = root / "desktop" / "plugin.js"
    return files + ([plugin] if plugin.exists() else [])


def main(root: Path = ROOT) -> int:
    stats = {"line": (0, "-"), "function": (0, "-")}
    problems, files = [], sources(root)
    for path in files:
        problems += check_file(path, path.relative_to(root).as_posix(), stats)
    for problem in problems:
        print(problem)
    verdict = "FAILED" if problems else "ok"
    print(f"jslint: {verdict}: {len(files)} files, longest line {stats['line'][0]} ({stats['line'][1]}), "
          f"longest function {stats['function'][0]} lines ({stats['function'][1]})")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT))
