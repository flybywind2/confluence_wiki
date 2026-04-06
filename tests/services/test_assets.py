from app.services.assets import build_image_markdown


def test_image_markdown_includes_local_asset_and_caption():
    rendered = build_image_markdown(
        image_path="assets/example.png",
        alt_text="example",
        caption="시스템 구성도를 설명하는 다이어그램이다.",
    )

    assert "![example](assets/example.png)" in rendered
    assert "시스템 구성도" in rendered
