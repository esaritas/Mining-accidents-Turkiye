"""Contract tests for the dashboard template and its two build outputs.

Role in the evidence flow: none directly — these guard the *presentation*
build. ``artifact.py`` extracts four regions from ``dashboard/index.html`` by
regular expression, and until now nothing checked that those regions still
exist. A template edit could silently ship a partial public page while the
whole suite stayed green.
"""

from __future__ import annotations

import json
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
    data_js = tmp_path / "TEST-data.js"
    data_js.write_text('window.MINING_DATA = {"incidents": []};\n', encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    try:
        artifact.build_artifact(
            conn,
            public_dir=tmp_path,
            template_path=template,
            output_path=out,
            data_js_path=data_js,
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


def test_database_build_does_not_silently_fall_back(tmp_path: Path) -> None:
    with sqlite3.connect(":memory:") as conn, pytest.raises(FileNotFoundError):
        artifact.build_artifact(conn, public_dir=tmp_path, output_path=tmp_path / "TEST.html")
    assert not (tmp_path / "TEST.html").exists()


def test_database_error_is_not_hidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object) -> dict[str, object]:
        raise sqlite3.OperationalError("TEST database failure")

    monkeypatch.setattr(artifact, "build_payload", broken)
    with sqlite3.connect(":memory:") as conn, pytest.raises(sqlite3.OperationalError):
        artifact.build_artifact(conn, output_path=tmp_path / "TEST.html")


def test_embedded_source_text_cannot_close_script(tmp_path: Path) -> None:
    payload = {"TEST-title": "</script><script>window.TEST_ATTACK = true</script><!--"}
    data_js = tmp_path / "TEST-data.js"
    data_js.write_text("window.MINING_DATA = " + json.dumps(payload) + ";\n", encoding="utf-8")
    output = artifact.build_artifact(
        None, data_js_path=data_js, output_path=tmp_path / "nested" / "TEST.html"
    ).read_text(encoding="utf-8")
    embedded = re.search(r"<script>window.MINING_DATA = (.*?);</script>", output, re.S)[1]
    assert "<" not in embedded
    assert json.loads(embedded) == payload
    assert output.count("<script>") == 2


def test_data_js_must_be_a_json_assignment(tmp_path: Path) -> None:
    data_js = tmp_path / "TEST-data.js"
    data_js.write_text('window.MINING_DATA = {}; alert("TEST");', encoding="utf-8")
    with pytest.raises(ValueError, match="generated window.MINING_DATA"):
        artifact._payload_from_js(data_js)
