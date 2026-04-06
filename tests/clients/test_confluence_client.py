from app.clients.confluence import ConfluenceClient
from app.core.config import Settings


def test_client_uses_mirror_for_reads_and_disables_ssl_verification(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)

    client = ConfluenceClient(settings)

    assert client.base_url == "https://mirror.example.com/confluence"
    assert client.verify_ssl is False
    assert client.build_page_url("123").endswith("pageId=123")
