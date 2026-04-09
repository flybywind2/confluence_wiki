from app.core.markdown import extract_wiki_links, render_markdown


def test_render_markdown_supports_obsidian_wikilinks_and_embeds():
    markdown = "\n".join(
        [
            "[[spaces/DEMO/pages/root-page-100|Root Page]]",
            "",
            "![[spaces/DEMO/assets/diagram.png]]",
            "",
            "> [!info] 이미지 설명",
            "> 시스템 구성도",
        ]
    )

    html = render_markdown(markdown)

    assert '/spaces/DEMO/pages/root-page-100' in html
    assert 'Root Page' in html
    assert '/wiki-static/spaces/DEMO/assets/diagram.png' in html
    assert '이미지 설명' in html


def test_extract_wiki_links_ignores_embeds_and_parses_obsidian_targets():
    markdown = "\n".join(
        [
            "[[spaces/DEMO/pages/root-page-100|Root Page]]",
            "![[spaces/DEMO/assets/diagram.png]]",
            "[[knowledge/keywords/운영|운영]]",
        ]
    )

    links = extract_wiki_links(markdown)

    assert links == [
        "spaces/DEMO/pages/root-page-100",
        "knowledge/keywords/운영",
    ]


def test_render_markdown_supports_pipe_tables():
    markdown = "\n".join(
        [
            "| 항목 | 값 |",
            "| --- | --- |",
            "| 상태 | 정상 |",
            "| 지연 | 3초 |",
        ]
    )

    html = render_markdown(markdown)

    assert "<table>" in html
    assert "<thead>" in html
    assert "<tbody>" in html
    assert "<th>항목</th>" in html
    assert "<td>정상</td>" in html
