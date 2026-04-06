from __future__ import annotations

from bs4 import BeautifulSoup


def _cell_text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


def markdown_table_from_html(soup: BeautifulSoup) -> str:
    rows = soup.find_all("tr")
    if not rows:
        return str(soup)

    rendered_rows: list[list[str]] = []
    for row in rows:
        cells = row.find_all(["th", "td"])
        if cells:
            rendered_rows.append([_cell_text(cell) for cell in cells])

    if not rendered_rows:
        return str(soup)

    header = rendered_rows[0]
    body = rendered_rows[1:] or [[]]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        padded = row + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(padded[: len(header)]) + " |")
    return "\n".join(lines)


def render_table_block(table_html: str) -> str:
    soup = BeautifulSoup(table_html, "html.parser")
    if soup.find(attrs={"rowspan": True}) or soup.find(attrs={"colspan": True}):
        return str(soup)
    return markdown_table_from_html(soup)
