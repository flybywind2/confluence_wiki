# Keyword Pages Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace concept-centric knowledge pages with frequency-based keyword pages generated from Confluence raw content.

**Architecture:** Keep raw pages and entity docs as internal sources, then build deterministic keyword clusters from token frequency and expose keyword documents as the primary knowledge layer in the UI, search, assistant, and knowledge graph.

**Tech Stack:** FastAPI, SQLAlchemy, markdown file store, pytest

---

### Task 1: Update knowledge kind definitions

**Files:**
- Modify: `D:/Python/confluence_wiki/repo_clone/app/core/knowledge.py`
- Test: `D:/Python/confluence_wiki/repo_clone/tests/api/test_api_endpoints.py`

**Step 1: Write the failing test**

Update API expectations so knowledge graph and home/search look for `keyword` labels instead of `concept`.

**Step 2: Run test to verify it fails**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/api/test_api_endpoints.py -q`
Expected: FAIL because UI and graph still expose concept docs.

**Step 3: Write minimal implementation**

Add `keyword -> keywords` segment and label mapping.

**Step 4: Run test to verify it passes**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/api/test_api_endpoints.py -q`
Expected: target tests pass or fail later on generation gaps only.

### Task 2: Replace concept generation with keyword generation

**Files:**
- Modify: `D:/Python/confluence_wiki/repo_clone/app/services/knowledge_service.py`
- Test: `D:/Python/confluence_wiki/repo_clone/tests/integration/test_demo_seed.py`
- Test: `D:/Python/confluence_wiki/repo_clone/tests/integration/test_end_to_end_sync.py`

**Step 1: Write the failing test**

Change integration tests to expect `knowledge/keywords/*.md` outputs and keyword-oriented index content.

**Step 2: Run test to verify it fails**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/integration/test_demo_seed.py D:/Python/confluence_wiki/repo_clone/tests/integration/test_end_to_end_sync.py -q`
Expected: FAIL because the service still writes concept docs.

**Step 3: Write minimal implementation**

Implement deterministic keyword extraction, keyword-to-page assignment, and keyword page materialization. Remove concept rebuild output.

**Step 4: Run test to verify it passes**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/integration/test_demo_seed.py D:/Python/confluence_wiki/repo_clone/tests/integration/test_end_to_end_sync.py -q`
Expected: PASS

### Task 3: Update graph and query surfaces

**Files:**
- Modify: `D:/Python/confluence_wiki/repo_clone/app/graph/builder.py`
- Modify: `D:/Python/confluence_wiki/repo_clone/app/api/routes.py`
- Modify: `D:/Python/confluence_wiki/repo_clone/app/services/wiki_qa.py`
- Test: `D:/Python/confluence_wiki/repo_clone/tests/api/test_api_endpoints.py`

**Step 1: Write the failing test**

Expect knowledge graph edges and assistant search filters to use `keyword`.

**Step 2: Run test to verify it fails**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/api/test_api_endpoints.py -q`
Expected: FAIL on knowledge graph edge/node kinds.

**Step 3: Write minimal implementation**

Swap concept-aware graph/query logic to keyword-aware logic while preserving analysis/lint/synthesis behavior.

**Step 4: Run test to verify it passes**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/api/test_api_endpoints.py -q`
Expected: PASS

### Task 4: Refresh docs and verify end-to-end

**Files:**
- Modify: `D:/Python/confluence_wiki/repo_clone/README.md`
- Test: `D:/Python/confluence_wiki/repo_clone/tests/api/test_pages.py`
- Test: `D:/Python/confluence_wiki/repo_clone/tests/services/test_lint_service.py`

**Step 1: Write the failing test**

Add or update documentation-sensitive assertions only if behavior exposure changed.

**Step 2: Run test to verify it fails**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/api/test_pages.py D:/Python/confluence_wiki/repo_clone/tests/services/test_lint_service.py -q`
Expected: FAIL only if stale labels remain.

**Step 3: Write minimal implementation**

Update README and any remaining labels or template copy.

**Step 4: Run test to verify it passes**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/api/test_pages.py D:/Python/confluence_wiki/repo_clone/tests/services/test_lint_service.py -q`
Expected: PASS

### Task 5: Final verification

**Files:**
- Verify only

**Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass

**Step 2: Verify browser-visible behavior if needed**

Run the app locally and verify:
- home shows keyword pages
- search prefers keyword pages
- knowledge graph uses keyword nodes

**Step 3: Commit**

```bash
git add .
git commit -m "feat: generate keyword-based wiki pages"
```
