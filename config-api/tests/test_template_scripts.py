"""Controllo statico degli <script> inline nei template Jinja2.

Una stringa JS "..." spezzata da un a capo letterale (invece di \\n) è un
SyntaxError che blocca l'intero blocco <script> della pagina — visto in
idps/list.html.j2: tab SPID non più cliccabili.
"""
import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"
SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
# Rimuove escape (\" \\) e commenti di riga prima di contare i doppi apici.
ESCAPE_RE = re.compile(r"\\.")
LINE_COMMENT_RE = re.compile(r"^\s*//.*$")

TEMPLATES = sorted(TEMPLATES_DIR.rglob("*.j2"))


def _unterminated_lines(source: str) -> list[tuple[int, str]]:
    bad = []
    for match in SCRIPT_RE.finditer(source):
        start_line = source.count("\n", 0, match.start(1)) + 1
        for offset, line in enumerate(match.group(1).split("\n")):
            if LINE_COMMENT_RE.match(line):
                continue
            if ESCAPE_RE.sub("", line).count('"') % 2:
                bad.append((start_line + offset, line.strip()))
    return bad


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: str(p.relative_to(TEMPLATES_DIR)))
def test_inline_script_strings_not_split_across_lines(template):
    bad = _unterminated_lines(template.read_text(encoding="utf-8"))
    assert not bad, f"Stringa JS non chiusa sulla riga (usare \\n, non a capo letterale): {bad}"


def test_detector_catches_literal_newline():
    source = '<script>\nconfirm("riga uno.\n\n" + "due");\n</script>'
    assert _unterminated_lines(source)
