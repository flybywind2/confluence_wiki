# Knowledge Web Editing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add web-based editing for user-visible knowledge markdown documents and remove space key prefixes from generated knowledge and synthesis titles.

**Architecture:** Add edit routes and a markdown editing template for knowledge and synthesis pages, then persist edits directly back to the markdown files while refreshing metadata and indexes. Keep raw Confluence pages read-only and limit edits to knowledge-first documents so the feature matches the existing file-based wiki model.

**Tech Stack:** FastAPI, Jinja2 templates, SQLAlchemy, markdown file storage, pytest

---

### Task 1: Title generation cleanup

**Files:**
- Modify: `app/services/knowledge_service.py`
- Modify: `app/services/index_builder.py`
- Test: `tests/api/test_pages.py`
- Test: `tests/integration/test_demo_seed.py`
- Test: `tests/integration/test_end_to_end_sync.py`

**Step 1: Write the failing tests**

Add assertions that generated concept and synthesis titles no longer include the space key prefix.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests\api\test_pages.py::test_synthesis_route_renders_space_summary -q`
Expected: FAIL because the page still renders `DEMO Synthesis`.

**Step 3: Write minimal implementation**

Update title and heading generation so UI-visible knowledge/synthesis titles render as `핵심 개념`, `운영과 런북`, `Synthesis`, `Lint Report`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests\api\test_pages.py::test_synthesis_route_renders_space_summary -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/knowledge_service.py app/services/index_builder.py tests/api/test_pages.py tests/integration/test_demo_seed.py tests/integration/test_end_to_end_sync.py
git commit -m "refactor: remove space key prefixes from wiki titles"
```

### Task 2: Knowledge markdown edit routes and template

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/templates/page.html`
- Create: `app/templates/page_edit.html`
- Modify: `app/static/app.css`
- Test: `tests/api/test_pages.py`

**Step 1: Write the failing tests**

Add route tests for:
- knowledge page shows an `편집` link
- raw page does not show the link
- edit form renders current markdown
- POST save redirects and updates rendered content

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests\api\test_pages.py::test_knowledge_edit_form_renders_markdown_body -q`
Expected: FAIL because the edit route does not exist yet.

**Step 3: Write minimal implementation**

Add GET/POST edit routes for user-visible knowledge docs and synthesis, plus a simple markdown textarea template and document action buttons.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests\api\test_pages.py::test_knowledge_edit_form_renders_markdown_body tests\api\test_pages.py::test_knowledge_edit_save_updates_rendered_content -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app/api/routes.py app/templates/page.html app/templates/page_edit.html app/static/app.css tests/api/test_pages.py
git commit -m "feat: add web editing for knowledge markdown"
```

### Task 3: File persistence and metadata refresh

**Files:**
- Modify: `app/core/markdown.py`
- Modify: `app/services/knowledge_service.py`
- Test: `tests/api/test_pages.py`

**Step 1: Write the failing tests**

Add assertions that saving:
- updates the markdown file body
- refreshes knowledge summary/index metadata
- preserves raw page read-only behavior

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests\api\test_pages.py::test_knowledge_edit_save_updates_rendered_content -q`
Expected: FAIL because the file and DB metadata are not refreshed yet.

**Step 3: Write minimal implementation**

Add markdown frontmatter/body read-write helpers and a knowledge service update path that writes the file, refreshes summary/updated_at, and rebuilds indexes for the space.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests\api\test_pages.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app/core/markdown.py app/services/knowledge_service.py tests/api/test_pages.py
git commit -m "feat: persist edited knowledge markdown"
```

### Task 4: Full verification

**Files:**
- Verify only

**Step 1: Run targeted verification**

Run: `python -m pytest tests\api\test_pages.py tests\integration\test_demo_seed.py tests\integration\test_end_to_end_sync.py -q`
Expected: PASS

**Step 2: Run full verification**

Run: `python -m pytest -q`
Expected: PASS

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: add knowledge editing workflow"
```
