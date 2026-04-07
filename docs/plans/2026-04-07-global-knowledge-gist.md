# Global Knowledge And Gist Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the wiki into a gist-aligned global knowledge base where raw pages remain space-scoped, but knowledge/query/lint operate globally and a user can build wiki pages directly from raw-file keyword search.

**Architecture:** Keep raw pages and page history under source spaces, but store user-facing knowledge pages in one canonical global layer with `/knowledge/...` routes. Use a hidden internal space only as storage metadata, and treat visible spaces purely as provenance filters. Add a raw-search topic builder and global lint path, then validate with a 10-document HN run and browser review.

**Tech Stack:** FastAPI, SQLAlchemy, markdown files, Jinja2, OpenAI-compatible LLM client, Chrome DevTools, pytest

---

### Task 1: Add Global Knowledge Conventions

**Files:**
- Modify: `app/core/knowledge.py`
- Modify: `app/core/obsidian.py`
- Modify: `app/core/markdown.py`
- Modify: `app/services/wiki_writer.py`
- Test: `tests/core/test_global_knowledge_paths.py`

**Step 1: Write the failing test**

Add tests that verify:

- global knowledge href is `/knowledge/keywords/topic`
- global obsidian links render to `knowledge/keywords/topic`
- markdown rendering converts `[[knowledge/keywords/topic|Label]]` into the global route
- legacy `spaces/<SPACE>/knowledge/...` links still resolve

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_global_knowledge_paths.py -q`

Expected: FAIL because global knowledge helpers do not exist yet.

**Step 3: Write minimal implementation**

- add internal global knowledge constants
- add canonical global href helpers
- update obsidian targets for global knowledge docs
- update markdown route hydration for `knowledge/...`
- update writer path so global knowledge markdown is stored outside source spaces

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/core/test_global_knowledge_paths.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add app/core/knowledge.py app/core/obsidian.py app/core/markdown.py app/services/wiki_writer.py tests/core/test_global_knowledge_paths.py
git commit -m "feat: add global knowledge routing conventions"
```

### Task 2: Move Knowledge Generation To A Global Layer

**Files:**
- Modify: `app/services/knowledge_service.py`
- Modify: `app/services/index_builder.py`
- Modify: `app/services/sync_service.py`
- Modify: `app/services/lint_service.py`
- Test: `tests/services/test_knowledge_service.py`
- Test: `tests/integration/test_end_to_end_sync.py`

**Step 1: Write the failing test**

Add tests that verify:

- two raw pages from different spaces contributing to the same topic create one knowledge doc
- per-space filtered indexes reference the same global doc
- sync rebuild path creates global keyword docs instead of per-space duplicates

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_knowledge_service.py tests/integration/test_end_to_end_sync.py -q`

Expected: FAIL because knowledge generation is still space-bound.

**Step 3: Write minimal implementation**

- create/get the internal hidden global knowledge space
- rebuild keywords globally across all visible spaces
- store source space provenance in frontmatter/source refs
- rebuild global index plus per-space filtered indexes
- rebuild global lint after knowledge rebuild
- keep raw pages and raw history untouched

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_knowledge_service.py tests/integration/test_end_to_end_sync.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add app/services/knowledge_service.py app/services/index_builder.py app/services/sync_service.py app/services/lint_service.py tests/services/test_knowledge_service.py tests/integration/test_end_to_end_sync.py
git commit -m "feat: make knowledge generation global"
```

### Task 3: Add Global Query And Keyword-To-Wiki Build

**Files:**
- Modify: `app/services/wiki_qa.py`
- Modify: `app/api/routes.py`
- Modify: `app/templates/base.html`
- Modify: `app/static/wiki-assistant.js`
- Create: `tests/services/test_topic_builder.py`
- Modify: `tests/api/test_wiki_qa_api.py`

**Step 1: Write the failing test**

Add tests that verify:

- query uses global knowledge docs by default
- a keyword build request searches raw pages across all spaces
- the build result creates or updates one global keyword page

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_topic_builder.py tests/api/test_wiki_qa_api.py -q`

Expected: FAIL because no keyword-build path exists yet.

**Step 3: Write minimal implementation**

- add raw-page search helper in `KnowledgeService`
- add `build_topic_from_query(...)`
- add API endpoint for topic build
- add simple UI entry point in sidebar or modal
- refresh global index, graph, and lint after building a topic

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_topic_builder.py tests/api/test_wiki_qa_api.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add app/services/wiki_qa.py app/api/routes.py app/templates/base.html app/static/wiki-assistant.js tests/services/test_topic_builder.py tests/api/test_wiki_qa_api.py
git commit -m "feat: add raw-search keyword wiki builder"
```

### Task 4: Add Global Lint Entry Points And Logging

**Files:**
- Modify: `app/services/lint_service.py`
- Modify: `app/services/index_builder.py`
- Modify: `app/cli.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`
- Test: `tests/services/test_lint_service.py`

**Step 1: Write the failing test**

Add tests that verify:

- `lint` can run explicitly from CLI
- global lint doc is generated
- lint log entries are appended

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py tests/services/test_lint_service.py -q`

Expected: FAIL because explicit global lint command/path does not exist yet.

**Step 3: Write minimal implementation**

- add explicit CLI `lint`
- add global lint log support
- document recommendation: lightweight lint after ingest/build, full lint daily

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py tests/services/test_lint_service.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add app/services/lint_service.py app/services/index_builder.py app/cli.py README.md tests/test_cli.py tests/services/test_lint_service.py
git commit -m "feat: add explicit global lint workflow"
```

### Task 5: Update Routes And Templates For Global Knowledge

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/templates/index.html`
- Modify: `app/templates/page.html`
- Modify: `app/templates/page_edit.html`
- Test: `tests/api/test_pages.py`
- Test: `tests/api/test_api_endpoints.py`

**Step 1: Write the failing test**

Add tests that verify:

- canonical knowledge pages are served at `/knowledge/...`
- legacy `/spaces/<space>/knowledge/...` routes still work
- space pages filter global knowledge by provenance
- editing still works for global keyword/analysis/lint docs

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_pages.py tests/api/test_api_endpoints.py -q`

Expected: FAIL because routes are still space-bound.

**Step 3: Write minimal implementation**

- add canonical global knowledge route
- keep compatibility route for old URLs
- update list/search rendering to use global docs
- update page/edit rendering and source-space context

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_pages.py tests/api/test_api_endpoints.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add app/api/routes.py app/templates/index.html app/templates/page.html app/templates/page_edit.html tests/api/test_pages.py tests/api/test_api_endpoints.py
git commit -m "feat: serve global knowledge pages"
```

### Task 6: Rebuild HN With 10 Sources And Verify UX

**Files:**
- Modify: `app/demo_seed.py` only if needed for helper reuse
- Create: `tests/integration/test_hn_global_knowledge.py`
- No permanent fixture file required; use temp DB/wiki roots in test

**Step 1: Write the failing test**

Add an integration test that simulates multiple source pages across one or more spaces and verifies:

- one global keyword page merges shared topics
- raw history remains per-page
- filtered HN view shows curated topics instead of fragment spam

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_hn_global_knowledge.py -q`

Expected: FAIL before the final HN workflow is stable.

**Step 3: Write minimal implementation**

- finalize any pruning and compatibility logic needed for realistic HN article runs
- run an actual 10-document HN import with the chosen Ollama model
- inspect resulting global docs in the browser

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_hn_global_knowledge.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/integration/test_hn_global_knowledge.py
git commit -m "test: cover global HN knowledge aggregation"
```

### Task 7: Final Verification And Push

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/plans/2026-04-07-global-knowledge-gist-design.md`

**Step 1: Run focused tests**

Run:

```bash
python -m pytest tests/core/test_global_knowledge_paths.py -q
python -m pytest tests/services/test_knowledge_service.py tests/services/test_topic_builder.py tests/services/test_lint_service.py -q
python -m pytest tests/api/test_pages.py tests/api/test_api_endpoints.py tests/api/test_wiki_qa_api.py -q
python -m pytest tests/integration/test_end_to_end_sync.py tests/integration/test_hn_global_knowledge.py -q
```

Expected: PASS

**Step 2: Run full suite**

Run:

```bash
python -m pytest -q
```

Expected: PASS

**Step 3: Browser verification**

Verify:

- HN space has 10 raw pages
- global knowledge pages are readable and non-fragmented
- raw page history is visible
- keyword-build UI creates/updates a global wiki page
- graph view works in global knowledge mode

**Step 4: Update docs**

- update `AGENTS.md` to reflect global knowledge ownership
- update `README.md` with global routes and lint recommendations

**Step 5: Commit and push**

```bash
git add AGENTS.md README.md docs/plans/2026-04-07-global-knowledge-gist-design.md docs/plans/2026-04-07-global-knowledge-gist.md
git commit -m "feat: align wiki with global knowledge workflow"
git push origin main
```
