from pathlib import Path

from app.parser.tables import render_table_block


def test_simple_table_becomes_markdown():
    html = Path("tests/fixtures/simple_table_storage.html").read_text(encoding="utf-8")
    rendered = render_table_block(html)

    assert "| Name | Role |" in rendered


def test_complex_table_falls_back_to_html():
    html = Path("tests/fixtures/complex_table_storage.html").read_text(encoding="utf-8")
    rendered = render_table_block(html)

    assert "<table" in rendered
    assert "rowspan" in rendered
