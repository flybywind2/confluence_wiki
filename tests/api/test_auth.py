from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import User
from app.db.session import create_session_factory
from app.demo_seed import seed_demo_content
from app.main import create_app


def _make_app(tmp_path, sample_settings_dict):
    settings = Settings.model_validate(
        {
            **sample_settings_dict,
            "WIKI_ROOT": str(tmp_path / "wiki"),
            "CACHE_ROOT": str(tmp_path / "cache"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        }
    )
    seed_demo_content(settings=settings)
    app = create_app(settings=settings, allow_test_fallback=False)
    return settings, app


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_login_page_renders_and_anonymous_user_is_redirected(tmp_path, sample_settings_dict):
    _settings, app = _make_app(tmp_path, sample_settings_dict)
    client = TestClient(app)

    login_response = client.get("/login")
    home_response = client.get("/", follow_redirects=False)

    assert login_response.status_code == 200
    assert "로그인" in login_response.text
    assert home_response.status_code == 303
    assert home_response.headers["location"] == "/login"


def test_viewer_cannot_open_knowledge_edit_form(tmp_path, sample_settings_dict):
    settings, app = _make_app(tmp_path, sample_settings_dict)
    client = TestClient(app)

    session = create_session_factory(settings.database_url)()
    try:
        viewer = session.scalar(select(User).where(User.username == "viewer"))
        assert viewer is not None
    finally:
        session.close()

    login_response = _login(client, "viewer", "viewer-pass")
    edit_response = client.get("/knowledge/keywords/운영-대시보드/edit", follow_redirects=False)

    assert login_response.status_code == 303
    assert edit_response.status_code == 403


def test_admin_can_open_user_management_page(tmp_path, sample_settings_dict):
    _settings, app = _make_app(tmp_path, sample_settings_dict)
    client = TestClient(app)

    login_response = _login(client, "admin", "admin-pass")
    users_response = client.get("/admin/users")

    assert login_response.status_code == 303
    assert users_response.status_code == 200
    assert "사용자 관리" in users_response.text
    assert "viewer" in users_response.text
