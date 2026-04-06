# Confluence Wiki Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a FastAPI service that syncs one or more Confluence Data Center spaces from a mirror endpoint into a markdown-file wiki with images, careful table handling, graph view, and external scheduler-driven updates.

**Architecture:** The application is split into a sync pipeline and a read-focused web app. Markdown pages and assets live on disk, while SQLAlchemy-managed metadata tracks spaces, pages, sync runs, graph edges, and assets in a DB that starts on SQLite but can later move to MySQL or PostgreSQL.

**Tech Stack:** Python 3.10.11+, FastAPI, Jinja2, SQLAlchemy 2.x, Alembic, httpx, pydantic-settings, pytest, BeautifulSoup4, markdown-it-py, frontmatter, networkx or direct graph JSON generation

---

### Task 1: Initialize project scaffold and configuration

**Files:**
- Create: `D:\Python\confluence_wiki\pyproject.toml`
- Create: `D:\Python\confluence_wiki\.gitignore`
- Create: `D:\Python\confluence_wiki\.env.example`
- Create: `D:\Python\confluence_wiki\app\__init__.py`
- Create: `D:\Python\confluence_wiki\app\main.py`
- Create: `D:\Python\confluence_wiki\app\core\config.py`
- Create: `D:\Python\confluence_wiki\tests\core\test_config.py`

**Step 1: Write the failing test**

```python
from app.core.config import Settings


def test_settings_load_required_confluence_and_llm_fields():
    settings = Settings.model_validate(
        {
            "CONF_MIRROR_BASE_URL": "https://mirror.example.com/confluence",
            "CONF_PROD_BASE_URL": "https://prod.example.com/confluence",
            "CONF_USERNAME": "user",
            "CONF_PASSWORD": "pass",
            "CONF_VERIFY_SSL": False,
            "DATABASE_URL": "sqlite:///./data/db/app.db",
            "WIKI_ROOT": "./data/wiki",
            "CACHE_ROOT": "./data/cache",
            "LLM_BASE_URL": "http://api.net:8000/v1",
            "LLM_MODEL": "QWEN3",
            "VLM_BASE_URL": "http://api.net/vl/v1",
            "VLM_MODEL": "QWEN3-VL",
        }
    )

    assert settings.conf_verify_ssl is False
    assert settings.sync_rate_limit_per_minute == 10
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError` because config module does not exist yet.

**Step 3: Write minimal implementation**

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    conf_mirror_base_url: str = Field(alias="CONF_MIRROR_BASE_URL")
    conf_prod_base_url: str = Field(alias="CONF_PROD_BASE_URL")
    conf_username: str = Field(alias="CONF_USERNAME")
    conf_password: str = Field(alias="CONF_PASSWORD")
    conf_verify_ssl: bool = Field(default=False, alias="CONF_VERIFY_SSL")
    sync_rate_limit_per_minute: int = Field(default=10, alias="SYNC_RATE_LIMIT_PER_MINUTE")
```

Also add `pyproject.toml` dependencies and a minimal `FastAPI()` app in `app/main.py`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_config.py -v`
Expected: PASS

**Step 5: Commit**

Run:

```bash
git init
git add pyproject.toml .gitignore .env.example app tests
git commit -m "chore: initialize confluence wiki project"
```

Expected: repo initialized and first commit created.

### Task 2: Add database session and portable ORM models

**Files:**
- Create: `D:\Python\confluence_wiki\app\db\base.py`
- Create: `D:\Python\confluence_wiki\app\db\session.py`
- Create: `D:\Python\confluence_wiki\app\db\models.py`
- Create: `D:\Python\confluence_wiki\tests\db\test_models.py`

**Step 1: Write the failing test**

```python
from sqlalchemy import create_engine

from app.db.base import Base


def test_metadata_contains_core_tables():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert "spaces" in Base.metadata.tables
    assert "pages" in Base.metadata.tables
    assert "page_links" in Base.metadata.tables
    assert "sync_runs" in Base.metadata.tables
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_models.py -v`
Expected: FAIL because DB base and models are not defined.

**Step 3: Write minimal implementation**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

```python
class Space(Base):
    __tablename__ = "spaces"
    id = mapped_column(Integer, primary_key=True)
    space_key = mapped_column(String(100), unique=True, nullable=False, index=True)
```

Define the remaining tables from the design document using portable SQL types and string-based status fields.

**Step 4: Run test to verify it passes**

Run: `pytest tests/db/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/db tests/db
git commit -m "feat: add portable metadata schema"
```

### Task 3: Set up Alembic for future MySQL/PostgreSQL migration

**Files:**
- Create: `D:\Python\confluence_wiki\alembic.ini`
- Create: `D:\Python\confluence_wiki\alembic\env.py`
- Create: `D:\Python\confluence_wiki\alembic\script.py.mako`
- Create: `D:\Python\confluence_wiki\alembic\versions\<timestamp>_initial_schema.py`
- Modify: `D:\Python\confluence_wiki\pyproject.toml`
- Create: `D:\Python\confluence_wiki\tests\db\test_migrations.py`

**Step 1: Write the failing test**

```python
from alembic.config import Config
from alembic import command


def test_alembic_upgrade_runs_against_sqlite(tmp_path):
    db_path = tmp_path / "app.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")

    assert db_path.exists()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_migrations.py -v`
Expected: FAIL because Alembic config is missing.

**Step 3: Write minimal implementation**

```python
target_metadata = Base.metadata
```

Generate the initial migration from the ORM models and wire `alembic.ini` to `DATABASE_URL`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/db/test_migrations.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add alembic.ini alembic pyproject.toml tests/db
git commit -m "feat: add alembic migrations"
```

### Task 4: Implement Confluence client config, auth, and SSL behavior

**Files:**
- Create: `D:\Python\confluence_wiki\app\clients\confluence.py`
- Create: `D:\Python\confluence_wiki\tests\clients\test_confluence_client.py`

**Step 1: Write the failing test**

```python
from app.clients.confluence import ConfluenceClient
from app.core.config import Settings


def test_client_uses_mirror_for_reads_and_disables_ssl_verification():
    settings = Settings.model_validate(
        {
            "CONF_MIRROR_BASE_URL": "https://mirror.example.com/confluence",
            "CONF_PROD_BASE_URL": "https://prod.example.com/confluence",
            "CONF_USERNAME": "user",
            "CONF_PASSWORD": "pass",
            "CONF_VERIFY_SSL": False,
            "DATABASE_URL": "sqlite:///./data/db/app.db",
            "WIKI_ROOT": "./data/wiki",
            "CACHE_ROOT": "./data/cache",
            "LLM_BASE_URL": "http://api.net:8000/v1",
            "LLM_MODEL": "QWEN3",
            "VLM_BASE_URL": "http://api.net/vl/v1",
            "VLM_MODEL": "QWEN3-VL",
        }
    )

    client = ConfluenceClient(settings)

    assert client.base_url == "https://mirror.example.com/confluence"
    assert client.verify_ssl is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/clients/test_confluence_client.py -v`
Expected: FAIL because client class does not exist.

**Step 3: Write minimal implementation**

```python
class ConfluenceClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.conf_mirror_base_url.rstrip("/")
        self.prod_base_url = settings.conf_prod_base_url.rstrip("/")
        self.verify_ssl = settings.conf_verify_ssl
```

Use `httpx.AsyncClient(auth=(username, password), verify=settings.conf_verify_ssl, timeout=...)`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/clients/test_confluence_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/clients tests/clients
git commit -m "feat: add confluence client configuration"
```

### Task 5: Add shared rate limiter for the mirror API

**Files:**
- Create: `D:\Python\confluence_wiki\app\clients\rate_limit.py`
- Modify: `D:\Python\confluence_wiki\app\clients\confluence.py`
- Create: `D:\Python\confluence_wiki\tests\clients\test_rate_limit.py`

**Step 1: Write the failing test**

```python
import asyncio
import time

from app.clients.rate_limit import MinuteRateLimiter


async def test_rate_limiter_blocks_after_capacity():
    limiter = MinuteRateLimiter(limit=2, period_seconds=60)

    await limiter.acquire()
    await limiter.acquire()

    started = time.monotonic()
    waiter = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0.05)

    assert waiter.done() is False
    waiter.cancel()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/clients/test_rate_limit.py -v`
Expected: FAIL because limiter does not exist.

**Step 3: Write minimal implementation**

```python
class MinuteRateLimiter:
    def __init__(self, limit: int, period_seconds: int = 60) -> None:
        self.limit = limit
        self.period_seconds = period_seconds
        self._timestamps = deque()
        self._lock = asyncio.Lock()
```

Hook the limiter into every outbound Confluence request path.

**Step 4: Run test to verify it passes**

Run: `pytest tests/clients/test_rate_limit.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/clients tests/clients
git commit -m "feat: enforce mirror api rate limiting"
```

### Task 6: Build CQL window generation and sync request planning

**Files:**
- Create: `D:\Python\confluence_wiki\app\services\cql.py`
- Create: `D:\Python\confluence_wiki\app\services\sync_window.py`
- Create: `D:\Python\confluence_wiki\tests\services\test_sync_window.py`

**Step 1: Write the failing test**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.sync_window import build_day_before_yesterday_window


def test_builds_previous_two_days_window_in_local_timezone():
    now = datetime(2026, 4, 6, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    start, end = build_day_before_yesterday_window(now)

    assert start.isoformat() == "2026-04-04T00:00:00+09:00"
    assert end.isoformat() == "2026-04-04T23:59:59+09:00"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_sync_window.py -v`
Expected: FAIL because date window helper does not exist.

**Step 3: Write minimal implementation**

```python
def build_day_before_yesterday_window(now: datetime) -> tuple[datetime, datetime]:
    target = (now - timedelta(days=2)).date()
    start = datetime.combine(target, time.min, tzinfo=now.tzinfo)
    end = datetime.combine(target, time(23, 59, 59), tzinfo=now.tzinfo)
    return start, end
```

Also create CQL helpers that emit a space-scoped query with created and lastmodified bounds for the target day.

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_sync_window.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services tests/services
git commit -m "feat: add incremental sync time window logic"
```

### Task 7: Parse Confluence storage content and preserve complex tables safely

**Files:**
- Create: `D:\Python\confluence_wiki\app\parser\storage.py`
- Create: `D:\Python\confluence_wiki\app\parser\tables.py`
- Create: `D:\Python\confluence_wiki\tests\parser\test_tables.py`
- Create: `D:\Python\confluence_wiki\tests\fixtures\simple_table_storage.html`
- Create: `D:\Python\confluence_wiki\tests\fixtures\complex_table_storage.html`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/parser/test_tables.py -v`
Expected: FAIL because parser does not exist.

**Step 3: Write minimal implementation**

```python
def render_table_block(table_html: str) -> str:
    soup = BeautifulSoup(table_html, "html.parser")
    if soup.find(attrs={"rowspan": True}) or soup.find(attrs={"colspan": True}):
        return str(soup)
    return markdown_table_from_html(soup)
```

Then integrate table rendering into a broader storage-to-markdown parser.

**Step 4: Run test to verify it passes**

Run: `pytest tests/parser/test_tables.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/parser tests/parser tests/fixtures
git commit -m "feat: add confluence table parsing with html fallback"
```

### Task 8: Add asset download and VLM caption pipeline

**Files:**
- Create: `D:\Python\confluence_wiki\app\llm\text_client.py`
- Create: `D:\Python\confluence_wiki\app\llm\vision_client.py`
- Create: `D:\Python\confluence_wiki\app\services\assets.py`
- Create: `D:\Python\confluence_wiki\tests\services\test_assets.py`

**Step 1: Write the failing test**

```python
from app.services.assets import build_image_markdown


def test_image_markdown_includes_local_asset_and_caption():
    rendered = build_image_markdown(
        image_path="assets/example.png",
        alt_text="example",
        caption="시스템 구성도를 설명하는 다이어그램이다.",
    )

    assert "![example](assets/example.png)" in rendered
    assert "시스템 구성도" in rendered
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_assets.py -v`
Expected: FAIL because asset helpers do not exist.

**Step 3: Write minimal implementation**

```python
def build_image_markdown(image_path: str, alt_text: str, caption: str | None) -> str:
    lines = [f"![{alt_text}]({image_path})"]
    if caption:
        lines.append("")
        lines.append(f"> 이미지 설명: {caption}")
    return "\n".join(lines)
```

Wrap the provided OpenAI-compatible APIs in small adapter classes and keep provider headers inside that layer.

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_assets.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/llm app/services tests/services
git commit -m "feat: add asset rendering and vlm adapter"
```

### Task 9: Write wiki markdown files, per-space indexes, and logs

**Files:**
- Create: `D:\Python\confluence_wiki\app\services\wiki_writer.py`
- Create: `D:\Python\confluence_wiki\app\services\index_builder.py`
- Create: `D:\Python\confluence_wiki\tests\services\test_wiki_writer.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

from app.services.wiki_writer import write_page_markdown


def test_writes_space_scoped_markdown_with_frontmatter(tmp_path):
    page_path = write_page_markdown(
        root=tmp_path,
        space_key="DEMO",
        slug="demo/example-page",
        frontmatter={"page_id": "123", "title": "Example Page"},
        body="# Example Page\n\n본문",
    )

    content = Path(page_path).read_text(encoding="utf-8")
    assert "page_id" in content
    assert "# Example Page" in content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_wiki_writer.py -v`
Expected: FAIL because wiki writer does not exist.

**Step 3: Write minimal implementation**

```python
def write_page_markdown(root: Path, space_key: str, slug: str, frontmatter: dict, body: str) -> Path:
    page_dir = root / "spaces" / space_key / "pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    path = page_dir / f"{slug.split('/')[-1]}.md"
    text = frontmatter_to_yaml(frontmatter) + "\n" + body
    path.write_text(text, encoding="utf-8")
    return path
```

Then add index/log builders for per-space and global output.

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_wiki_writer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services tests/services
git commit -m "feat: add markdown wiki writer"
```

### Task 10: Store hierarchy and wiki links, then build graph JSON

**Files:**
- Create: `D:\Python\confluence_wiki\app\graph\builder.py`
- Create: `D:\Python\confluence_wiki\app\graph\schemas.py`
- Create: `D:\Python\confluence_wiki\tests\graph\test_builder.py`

**Step 1: Write the failing test**

```python
from app.graph.builder import build_graph_payload


def test_graph_payload_distinguishes_hierarchy_and_wiki_edges():
    payload = build_graph_payload(
        nodes=[{"id": 1, "title": "A", "space_key": "DEMO"}, {"id": 2, "title": "B", "space_key": "DEMO"}],
        edges=[
            {"source": 1, "target": 2, "link_type": "hierarchy"},
            {"source": 2, "target": 1, "link_type": "wiki"},
        ],
    )

    assert payload["edges"][0]["type"] == "hierarchy"
    assert payload["edges"][1]["type"] == "wiki"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/graph/test_builder.py -v`
Expected: FAIL because graph builder does not exist.

**Step 3: Write minimal implementation**

```python
def build_graph_payload(nodes: list[dict], edges: list[dict]) -> dict:
    return {
        "nodes": nodes,
        "edges": [{"source": e["source"], "target": e["target"], "type": e["link_type"]} for e in edges],
    }
```

Then add space filtering and static cache writing to `data/wiki/global/graph.json`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/graph/test_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/graph tests/graph
git commit -m "feat: add graph payload builder"
```

### Task 11: Create bootstrap and incremental sync orchestration

**Files:**
- Create: `D:\Python\confluence_wiki\app\services\sync_service.py`
- Create: `D:\Python\confluence_wiki\app\services\space_registry.py`
- Create: `D:\Python\confluence_wiki\app\cli.py`
- Create: `D:\Python\confluence_wiki\tests\services\test_sync_service.py`

**Step 1: Write the failing test**

```python
from app.services.sync_service import SyncPlan


def test_sync_plan_marks_incremental_scope_as_space_wide():
    plan = SyncPlan.for_incremental(space_key="DEMO")
    assert plan.scope == "space"
    assert plan.mode == "incremental"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_sync_service.py -v`
Expected: FAIL because sync service does not exist.

**Step 3: Write minimal implementation**

```python
@dataclass
class SyncPlan:
    mode: str
    scope: str
    space_key: str

    @classmethod
    def for_incremental(cls, space_key: str) -> "SyncPlan":
        return cls(mode="incremental", scope="space", space_key=space_key)
```

Then wire bootstrap descendant fetch and incremental CQL fetch into one service with DB persistence.

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_sync_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/cli.py app/services tests/services
git commit -m "feat: add sync orchestration and cli"
```

### Task 12: Build the FastAPI wiki UI with multi-space selector

**Files:**
- Create: `D:\Python\confluence_wiki\app\api\routes.py`
- Create: `D:\Python\confluence_wiki\app\templates\base.html`
- Create: `D:\Python\confluence_wiki\app\templates\index.html`
- Create: `D:\Python\confluence_wiki\app\templates\page.html`
- Create: `D:\Python\confluence_wiki\app\templates\graph.html`
- Create: `D:\Python\confluence_wiki\app\static\app.css`
- Create: `D:\Python\confluence_wiki\app\static\graph.js`
- Create: `D:\Python\confluence_wiki\tests\api\test_pages.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_index_page_renders_space_selector():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "space" in response.text.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_pages.py -v`
Expected: FAIL because routes and templates are not wired yet.

**Step 3: Write minimal implementation**

```python
@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "spaces": [], "selected_space": "all"},
    )
```

Add the page renderer, graph page, and search page with a clear space selection UI.

**Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_pages.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/api app/templates app/static tests/api
git commit -m "feat: add fastapi wiki ui"
```

### Task 13: Add graph/search/admin API endpoints

**Files:**
- Modify: `D:\Python\confluence_wiki\app\api\routes.py`
- Create: `D:\Python\confluence_wiki\tests\api\test_api_endpoints.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_graph_endpoint_returns_nodes_and_edges():
    client = TestClient(app)
    response = client.get("/api/graph")
    assert response.status_code == 200
    body = response.json()
    assert "nodes" in body
    assert "edges" in body
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_api_endpoints.py -v`
Expected: FAIL because JSON APIs are not implemented.

**Step 3: Write minimal implementation**

```python
@router.get("/api/graph")
async def graph_api() -> dict:
    return {"nodes": [], "edges": []}
```

Also add `/api/spaces`, `/api/search`, and protected `/admin/bootstrap` plus `/admin/sync`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_api_endpoints.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/api tests/api
git commit -m "feat: add graph search and admin endpoints"
```

### Task 14: Add integration tests for end-to-end wiki generation

**Files:**
- Create: `D:\Python\confluence_wiki\tests\integration\test_end_to_end_sync.py`
- Create: `D:\Python\confluence_wiki\tests\fixtures\confluence_search.json`
- Create: `D:\Python\confluence_wiki\tests\fixtures\confluence_page.json`
- Create: `D:\Python\confluence_wiki\tests\fixtures\confluence_attachment.json`

**Step 1: Write the failing test**

```python
def test_incremental_sync_creates_markdown_and_graph_artifacts(tmp_path):
    # Arrange: mock Confluence responses and temp DB/wiki roots
    # Act: run incremental sync
    # Assert: markdown file, index.md, log.md, graph.json all exist
    assert False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_end_to_end_sync.py -v`
Expected: FAIL because the orchestration is not complete.

**Step 3: Write minimal implementation**

Replace the placeholder assertion with a real test using mocked HTTP responses and complete any missing orchestration glue until it passes.

**Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_end_to_end_sync.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/integration tests/fixtures app
git commit -m "test: cover end-to-end sync flow"
```

### Task 15: Write operator docs and run full verification

**Files:**
- Create: `D:\Python\confluence_wiki\README.md`
- Modify: `D:\Python\confluence_wiki\.env.example`
- Modify: `D:\Python\confluence_wiki\docs\plans\2026-04-06-confluence-wiki-design.md`

**Step 1: Write the failing test**

There is no useful automated test here. Instead, define the verification checklist first:

```text
- local app boots
- alembic upgrade works
- bootstrap CLI works against mocked data
- incremental sync works against mocked data
- page UI renders
- graph API responds
```

**Step 2: Run verification to identify gaps**

Run: `pytest -v`
Expected: Some failures until missing glue or regressions are fixed.

**Step 3: Write minimal implementation**

Fill in missing documentation:

- required `.env` keys
- bootstrap command usage
- incremental sync command usage
- external scheduler example
- note that Confluence SSL verification is controlled by `CONF_VERIFY_SSL=false`
- note that production links are displayed to users while reads go to mirror

**Step 4: Run test to verify it passes**

Run:

```bash
pytest -v
python -m app.cli --help
python -c "from app.main import app; print(app.title)"
```

Expected:

- all tests PASS
- CLI help renders successfully
- FastAPI app imports without error

**Step 5: Commit**

```bash
git add README.md .env.example docs/plans app tests
git commit -m "docs: add operator guidance and final verification"
```

Plan complete and saved to `docs/plans/2026-04-06-confluence-wiki.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
