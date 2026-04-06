# LLM Knowledge Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the remaining `llm-wiki` features by introducing DB-backed knowledge pages, persisted assistant analyses, lint output, a richer wiki catalog index, and an `AGENTS.md` schema file.

**Architecture:** Keep the existing mirrored Confluence page pipeline intact and add a second document layer for LLM-authored markdown files. Both layers are stored on disk and indexed in the DB so FastAPI, search, graph, and the assistant can read them consistently.

**Tech Stack:** Python, FastAPI, SQLAlchemy 2.x, Alembic, Jinja2, pytest, markdown file storage, existing OpenAI-compatible assistant client.

---

### Task 1: Add failing tests for knowledge document storage and routes

**Files:**
- Modify: `tests/api/test_pages.py`
- Create: `tests/services/test_knowledge_service.py`
- Modify: `tests/integration/test_demo_seed.py`

**Step 1: Write the failing test**

Add tests that assert:

- `knowledge/entities`, `knowledge/concepts`, `knowledge/analyses` markdown files can be created and surfaced in the UI
- knowledge page routes render correctly
- the space index shows grouped knowledge entries with summaries

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_knowledge_service.py tests/api/test_pages.py -q`
Expected: FAIL because knowledge documents do not exist yet.

**Step 3: Write minimal implementation**

Add:

- `KnowledgeDocument` ORM model and migration
- markdown writer helpers
- knowledge page routes and templates

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_knowledge_service.py tests/api/test_pages.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app/db app/api app/services app/templates tests
git commit -m "feat: add knowledge wiki document layer"
```

### Task 2: Add failing tests for saved assistant analyses

**Files:**
- Modify: `tests/api/test_wiki_qa_api.py`
- Modify: `tests/services/test_wiki_qa.py`

**Step 1: Write the failing test**

Add tests that assert:

- assistant responses can be saved as analysis pages
- saved analysis pages contain question, answer, citations, and scope
- saved analysis pages appear in the index and can be queried later

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_wiki_qa_api.py tests/services/test_wiki_qa.py -q`
Expected: FAIL because no save-to-wiki operation exists.

**Step 3: Write minimal implementation**

Add:

- service method to persist an analysis page
- API route for saving a response
- assistant UI hook later in Task 4

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_wiki_qa_api.py tests/services/test_wiki_qa.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app/api app/services tests
git commit -m "feat: persist assistant analyses into wiki"
```

### Task 3: Add failing tests for lint output and index enrichment

**Files:**
- Create: `tests/services/test_lint_service.py`
- Modify: `tests/integration/test_end_to_end_sync.py`
- Modify: `tests/integration/test_demo_seed.py`

**Step 1: Write the failing test**

Add tests that assert:

- lint generation creates `knowledge/lint.md`
- lint file flags orphan/missing-summary/missing-history cases
- `index.md` includes grouped sections and one-line summaries for both mirrored pages and knowledge docs

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_lint_service.py tests/integration/test_end_to_end_sync.py -q`
Expected: FAIL because lint and enriched index do not exist.

**Step 3: Write minimal implementation**

Add:

- lint service
- index builder changes
- integration into sync and demo seed

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_lint_service.py tests/integration/test_end_to_end_sync.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services tests
git commit -m "feat: add wiki lint artifact and richer index"
```

### Task 4: Add schema document and assistant UI integration

**Files:**
- Create: `AGENTS.md`
- Modify: `app/static/wiki-assistant.js`
- Modify: `app/static/app.css`
- Modify: `app/templates/base.html`
- Modify: `README.md`

**Step 1: Write the failing test**

Add API/UI tests that assert:

- assistant response payload exposes save metadata
- save action can be triggered from the UI endpoint

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_wiki_qa_api.py tests/api/test_pages.py -q`
Expected: FAIL until UI/save integration is wired.

**Step 3: Write minimal implementation**

Add:

- `Save to Wiki` button in assistant modal
- API call to persist analyses
- `AGENTS.md` with maintenance rules
- docs update

**Step 4: Run full verification**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass.

Then run manual verification:

```bash
python -m app.demo_seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8768
```

Check:

- knowledge pages render
- assistant can save an analysis page
- synthesis, lint, and index reflect the new knowledge page

**Step 5: Commit**

```bash
git add AGENTS.md README.md app/static app/templates tests
git commit -m "feat: complete llm wiki knowledge workflows"
```
