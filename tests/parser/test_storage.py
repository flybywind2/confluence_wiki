from app.parser.storage import storage_to_markdown


def test_storage_converts_confluence_page_link():
    html = '<p><a href="/pages/viewpage.action?pageId=1234" data-linked-resource-id="1234">운영 대시보드</a></p>'

    rendered = storage_to_markdown(html)

    assert rendered == "[[pageid:1234|운영 대시보드]]"


def test_storage_preserves_nested_lists():
    html = "<ul><li>상위 항목<ul><li>하위 항목</li></ul></li><li>다음 항목</li></ul>"

    rendered = storage_to_markdown(html)

    assert "- 상위 항목" in rendered
    assert "  - 하위 항목" in rendered
    assert "- 다음 항목" in rendered


def test_storage_converts_info_macro_to_callout():
    html = (
        '<ac:structured-macro ac:name="info">'
        "<ac:rich-text-body><p>운영 전 mirror URL 연결 상태를 확인합니다.</p></ac:rich-text-body>"
        "</ac:structured-macro>"
    )

    rendered = storage_to_markdown(html)

    assert "> [!info] Info" in rendered
    assert "> 운영 전 mirror URL 연결 상태를 확인합니다." in rendered


def test_storage_converts_expand_macro_to_summary_callout():
    html = (
        '<ac:structured-macro ac:name="expand">'
        '<ac:parameter ac:name="title">세부 절차</ac:parameter>'
        "<ac:rich-text-body><p>첫 단계</p><ul><li>하위 체크</li></ul></ac:rich-text-body>"
        "</ac:structured-macro>"
    )

    rendered = storage_to_markdown(html)

    assert "> [!summary] 세부 절차" in rendered
    assert "> 첫 단계" in rendered
    assert "> - 하위 체크" in rendered


def test_storage_converts_code_macro_to_fenced_block():
    html = (
        '<ac:structured-macro ac:name="code">'
        '<ac:plain-text-body><![CDATA[print("hello")]]></ac:plain-text-body>'
        "</ac:structured-macro>"
    )

    rendered = storage_to_markdown(html)

    assert "```" in rendered
    assert 'print("hello")' in rendered


def test_storage_converts_attachment_image_macro_to_placeholder():
    html = '<ac:image><ri:attachment ri:filename="diagram.png"></ri:attachment></ac:image>'

    rendered = storage_to_markdown(html)

    assert rendered == "[[confluence-image:attachment:diagram.png|diagram.png]]"
