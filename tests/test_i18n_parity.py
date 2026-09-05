"""Both dashboard languages must define the same keys.

``t()`` falls back English -> raw key, so a key added to ``I18N.en`` but not to
``I18N.tr`` renders English inside the Turkish page and nothing fails. This
test is the only thing that catches it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE = Path("dashboard/index.html")


def _block(source: str, lang: str) -> str:
    """The `en: { ... }` / `tr: { ... }` object literal, by brace matching."""
    start = source.index(f"\n    {lang}: {{")
    open_brace = source.index("{", start)
    depth = 0
    for pos in range(open_brace, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace : pos + 1]
    raise AssertionError(f"unbalanced braces in I18N.{lang}")


def _keys(block: str) -> set[str]:
    """Top-level keys, plus `parent.child` for the nested label objects."""
    keys: set[str] = set()
    depth = 0
    parent = None
    for line in block.split("\n"):
        for name in re.findall(r"(?:^\s*|[{,]\s*)([a-z_][a-z0-9_]*)\s*:", line, flags=re.I):
            keys.add(name if depth <= 1 else f"{parent}.{name}")
        opened, closed = line.count("{"), line.count("}")
        if opened > closed and depth == 1:
            match = re.search(r"([a-z_][a-z0-9_]*)\s*:\s*\{", line, flags=re.I)
            if match:
                parent = match.group(1)
        depth += opened - closed
    return keys


@pytest.fixture(scope="module")
def blocks() -> tuple[set[str], set[str]]:
    source = TEMPLATE.read_text(encoding="utf-8")
    return _keys(_block(source, "en")), _keys(_block(source, "tr"))


def test_both_languages_define_the_same_keys(blocks: tuple[set[str], set[str]]) -> None:
    en, tr = blocks
    assert not (en - tr), f"missing from I18N.tr: {sorted(en - tr)}"
    assert not (tr - en), f"missing from I18N.en: {sorted(tr - en)}"


def test_key_set_is_not_trivially_small(blocks: tuple[set[str], set[str]]) -> None:
    """Guards the parser itself: if brace matching broke, the sets would be tiny."""
    en, _ = blocks
    assert len(en) > 120
