from app.services.assets import build_image_markdown


def test_image_markdown_uses_obsidian_embed_for_local_assets_and_callout_caption():
    rendered = build_image_markdown(
        image_path="spaces/DEMO/assets/example.png",
        alt_text="example",
        caption="시스템 구성도를 설명하는 다이어그램이다.",
    )

    assert "![[spaces/DEMO/assets/example.png]]" in rendered
    assert "[!info]" in rendered
    assert "시스템 구성도" in rendered
