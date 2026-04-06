from pathlib import Path

from app.services.wiki_writer import write_page_markdown


def test_writes_space_scoped_markdown_with_frontmatter(tmp_path):
    page_path = write_page_markdown(
        root=tmp_path,
        space_key="DEMO",
        slug="example-page-123",
        frontmatter={"page_id": "123", "title": "Example Page"},
        body="# Example Page\n\n본문",
    )

    content = Path(page_path).read_text(encoding="utf-8")
    assert "page_id" in content
    assert "# Example Page" in content
