# Persistent LLM Wiki Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the current Confluence markdown wiki into a persistent LLM-style wiki with per-page revision snapshots, append-only space logs, and cumulative synthesis pages.

**Architecture:** Extend the existing sync pipeline rather than replacing it. Keep the current latest-page markdown files, add history snapshots and synthesis/log files on disk, and expand the SQLAlchemy revision metadata so FastAPI can render current pages and historical pages from the same source of truth.

**Tech Stack:** Python, FastAPI, Jinja2, SQLAlchemy 2.x, pytest, markdown file storage, existing OpenAI-compatible text/VLM clients.

---

### Task 1: Add failing tests for persistent version storage

**Files:**
- Modify: `tests/services/test_sync_service.py`
- Modify: `tests/integration/test_demo_seed.py`

**Step 1: Write the failing test**

Add tests that assert:

- syncing a page writes `spaces/<SPACE>/history/<slug>/v0001.md`
- syncing a newer version writes `v0002.md`
- re-syncing the same version does not duplicate snapshot files
- `PageVersion.markdown_path` and `summary` are stored

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_sync_service.py -q`
Expected: FAIL because history snapshot metadata does not exist yet.

**Step 3: Write minimal implementation**

Add DB columns, snapshot file writing helpers, and sync-service logic for version-aware writes.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_sync_service.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/services/test_sync_service.py tests/integration/test_demo_seed.py app/db/models.py app/services
git commit -m "feat: persist wiki page history snapshots"
```

### Task 2: Add failing tests for append-only logs and synthesis pages

**Files:**
- Modify: `tests/services/test_sync_service.py`
- Modify: `tests/api/test_pages.py`

**Step 1: Write the failing test**

Add tests that assert:

- successful sync appends a new block to `spaces/<SPACE>/log.md` instead of rewriting old entries
- `spaces/<SPACE>/synthesis.md` is generated
- synthesis includes latest page links and summaries

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_sync_service.py tests/api/test_pages.py -q`
Expected: FAIL because append-only logging and synthesis generation do not exist.

**Step 3: Write minimal implementation**

Implement:

- append-only log builder
- synthesis file writer
- space home link to synthesis page

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_sync_service.py tests/api/test_pages.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/services/test_sync_service.py tests/api/test_pages.py app/services app/templates
git commit -m "feat: add append-only space logs and synthesis pages"
```

### Task 3: Add failing tests for history UI and routes

**Files:**
- Modify: `tests/api/test_pages.py`
- Modify: `tests/integration/test_demo_seed.py`

**Step 1: Write the failing test**

Add tests that assert:

- page detail shows revision links
- `/spaces/<SPACE>/pages/<slug>/history` renders the revision list
- `/spaces/<SPACE>/pages/<slug>/history/<version>` renders a historical snapshot

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_pages.py tests/integration/test_demo_seed.py -q`
Expected: FAIL because history routes and templates do not exist.

**Step 3: Write minimal implementation**

Add:

- history list route
- version detail route
- page template history section
- reusable template helpers for revision metadata

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_pages.py tests/integration/test_demo_seed.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/api/test_pages.py tests/integration/test_demo_seed.py app/api app/templates app/static
git commit -m "feat: add wiki page history views"
```

### Task 4: Update docs and verify end to end

**Files:**
- Modify: `README.md`
- Modify: `data/demo_seed/pages/DEMO/demo-home.md`
- Modify: `app/demo_seed.py`

**Step 1: Write the failing test**

Add or update integration expectations for:

- demo seed creates history files
- demo seed creates synthesis page

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_demo_seed.py -q`
Expected: FAIL until demo seed and docs are updated.

**Step 3: Write minimal implementation**

Update demo seed, README, and any sample navigation needed for manual verification.

**Step 4: Run full verification**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass.

Then run the app and manually verify:

```bash
python -m app.demo_seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Check:

- synthesis page is visible from space home
- page detail shows history links
- historical snapshot pages render
- `log.md` shows multiple entries after repeated sync/demo seed runs

**Step 5: Commit**

```bash
git add README.md app/demo_seed.py data/demo_seed tests
git commit -m "feat: add persistent llm wiki views and docs"
```
