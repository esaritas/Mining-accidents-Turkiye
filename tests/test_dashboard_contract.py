"""Contract tests for the dashboard template and its two build outputs.

Role in the evidence flow: none directly — these guard the *presentation*
build. ``artifact.py`` extracts four regions from ``dashboard/index.html`` by
regular expression, and until now nothing checked that those regions still
exist. A template edit could silently ship a partial public page while the
whole suite stayed green.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from mining_accidents import artifact

TEMPLATE = Path("dashboard/index.html")


@pytest.fixture(scope="module")
def template_html() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("pattern", "what"),
    [
        (r"<title>.*?</title>", "<title>"),
        (r"<style>.*?</style>", "<style> block"),
        (r"<main>.*?</main>", "<main> block"),
        (r"<script>\s*\(function.*?</script>", "page script"),
    ],
)
def test_artifact_regions_are_present(template_html: str, pattern: str, what: str) -> None:
    """Each region artifact.py extracts must still be findable."""
    assert artifact._extract(template_html, pattern, what)


def test_exactly_one_style_and_one_main(template_html: str) -> None:
    """A second <style> or <main> would be silently dropped by the non-greedy
    extraction, shipping a page missing half its rules."""
    assert template_html.count("<style>") == 1
    assert template_html.count("<main>") == 1
    assert template_html.count("</main>") == 1


def test_title_is_single_line(template_html: str) -> None:
    """The Pages workflow lifts the title with a line-oriented grep."""
    titles = re.findall(r"^<title>[^<\n]*</title>$", template_html, flags=re.M)
    assert len(titles) == 1


def test_page_script_opens_with_bare_iife(template_html: str) -> None:
    """The extraction requires a bare <script> whose body starts with `(function`."""
    assert re.search(r"<script>\s*\(function", template_html)


def test_build_artifact_assembles_a_page(tmp_path: Path) -> None:
    """A synthetic TEST- template exercises the whole assembly, including the
    .viz-root -> body rebinding the artifact host needs."""
    template = tmp_path / "TEST-template.html"
    template.write_text(
        "<html><head><title>TEST-title</title>\n"
        "<style>.viz-root { --x: 1; } body.viz-root { margin: 0; }</style>\n"
        '<script src="data.js"></script></head>\n'
        '<body class="viz-root"><main><h1>TEST-main</h1></main>\n'
        "<script>(function () { window.TEST = 1; })();</script></body></html>",
        encoding="utf-8",
    )
    out = tmp_path / "TEST-artifact.html"
    conn = sqlite3.connect(":memory:")  # no tables: exercises the data.js fallback
    try:
        artifact.build_artifact(
            conn,
            public_dir=tmp_path,
            template_path=template,
            output_path=out,
        )
    finally:
        conn.close()

    written = out.read_text(encoding="utf-8")
    assert "TEST-title" in written
    assert "TEST-main" in written
    assert "window.MINING_DATA" in written
    # the host owns <body>, so the class hook must be rebound and gone
    assert "viz-root" not in written
    assert "body { --x: 1; }" in written
    # no external references may survive into the self-contained artifact
    assert "<script src=" not in written
    assert "<link " not in written
