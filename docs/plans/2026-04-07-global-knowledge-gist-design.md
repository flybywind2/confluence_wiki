# Global Knowledge And Gist Alignment Design

## Goal

Confluence/GeekNews raw sources are still stored and versioned per source space, but the user-facing wiki, query flow, and lint flow should operate on a single global knowledge layer that merges the same topic across spaces into one page.

This also needs to align more closely with Karpathy's llm-wiki gist:

- raw sources are immutable input
- ingest updates many wiki pages
- query reads the wiki and can file results back
- lint periodically health-checks the wiki
- index and log guide both the user and the agent

## Current Gaps

The current implementation is only partially aligned with the gist.

- `INGEST`: raw page sync exists, but `knowledge` is rebuilt per-space, so the same topic is split across spaces.
- `QUERY`: Q&A exists and can save analyses, but there is no direct "build a wiki page from a keyword over all raw files" flow.
- `LINT`: lint exists, but it is per-space and mostly passive. It is not treated as a first-class global maintenance operation.
- `INDEX`: the system has `global/index.md`, but the user-facing wiki still behaves as if space is the primary divider.
- `LOG`: logging exists per-space, but the gist pattern wants a global chronological maintenance trail as well.

## Recommended Approach

### Option A: Full DB-level global knowledge refactor

Create a new global knowledge table/model independent from `Space`, migrate all current knowledge documents into it, and update all routes and services accordingly.

Pros:

- clean data model
- explicit separation between raw and knowledge layers

Cons:

- largest migration cost
- highest risk in current codebase

### Option B: Internal global knowledge space plus canonical global routes

Keep the existing `KnowledgeDocument.space_id` foreign key, but store all global wiki pages in a single hidden internal space. Expose them through canonical routes like `/knowledge/keywords/<slug>`, and treat real spaces only as source references and filters.

Pros:

- smallest viable refactor
- preserves most existing storage/model code
- delivers the user-visible behavior we want

Cons:

- internal model is less pure
- requires careful route/index/filter cleanup

### Option C: Keep per-space docs and add a global overlay

Leave per-space knowledge generation intact, then build a secondary merged layer on top.

Pros:

- low migration risk

Cons:

- duplicated pages remain
- query/lint complexity doubles
- violates the user's core requirement

## Recommendation

Use Option B.

The current codebase is deeply space-bound, so a hidden internal global space plus canonical global routes is the best balance of speed and correctness. Raw pages and their history remain space-scoped. Knowledge pages, search, query, keyword-build, and lint become global.

## Target Behavior

### Raw Layer

- Raw source pages stay under `spaces/<SPACE>/pages/`
- Raw history stays under `spaces/<SPACE>/history/<slug>/vNNNN.md`
- Space remains meaningful here because it is the source partition and sync boundary

### Global Knowledge Layer

- Canonical knowledge routes become `/knowledge/<kind>/<slug>`
- Canonical knowledge markdown lives outside source spaces
- The same topic from multiple spaces updates one page
- Knowledge documents record which source spaces and raw pages contributed evidence

### Space UX

- Space pages become filtered views over the global knowledge layer
- Selecting a space means "show knowledge pages supported by raw pages from this space"
- Space is a filter and provenance hint, not a wiki partition

## Gist Operation Mapping

### Ingest

Recommended behavior:

1. Read new raw sources
2. Update raw markdown and raw history
3. Recompute affected or global knowledge documents
4. Update index and log
5. Run lint for the updated knowledge state

This means a single ingest may touch many knowledge pages, which matches the gist.

### Query

Recommended behavior:

1. Search the global wiki first
2. Fall back to raw pages when needed
3. Optionally save the answer back as a global analysis page
4. Add a new "build topic page from keyword" workflow that searches all raw files and materializes a wiki page

This directly addresses the user's request and matches the gist pattern that query outputs can become new wiki pages.

### Lint

Recommended behavior:

- Run lightweight global lint after any ingest or keyword-build operation
- Add explicit `lint` CLI/admin/API flow for full health checks
- Recommend a scheduled full global lint once daily

Why daily full lint is worth it:

- lint is cheap compared to ingest
- it catches stale relationships, orphan topics, missing backlinks, weak wiki pages, and coverage gaps
- this is exactly the kind of maintenance the gist expects to compound over time

The recommendation is:

- automatic lint after each ingest/build
- scheduled full lint once daily

## New User Workflow

### Build Topic From Keyword

The user enters a keyword or phrase.

The system:

1. searches all raw markdown files
2. ranks matching raw pages
3. writes or updates one global wiki page for that keyword
4. stores source links and source spaces
5. refreshes index, graph, and lint

### Readability Goal

After ingesting 10 documents, a human should feel that:

- the original scattered pages are still preserved and historically traceable
- the wiki pages are cleaner than the raw pages
- related articles from different spaces accumulate in one topic page
- graph and query operate on the organized knowledge layer, not isolated source silos

## Files Likely Affected

- `app/core/knowledge.py`
- `app/core/obsidian.py`
- `app/core/markdown.py`
- `app/services/wiki_writer.py`
- `app/services/knowledge_service.py`
- `app/services/wiki_qa.py`
- `app/services/lint_service.py`
- `app/services/index_builder.py`
- `app/services/sync_service.py`
- `app/api/routes.py`
- `app/cli.py`
- `app/templates/base.html`
- `app/templates/index.html`
- `app/templates/page.html`
- `app/static/wiki-assistant.js`
- tests for routes/services/integration

## Risks

- Existing tests assume knowledge docs are per-space
- Legacy `/spaces/<space>/knowledge/...` links must remain usable
- Keyword generation quality can still degrade if global merging is too loose
- Large global rebuilds can be slow if every operation uses the full LLM path

## Risk Mitigation

- Keep raw pages/history untouched
- Use canonical global knowledge routes, but preserve legacy space knowledge routes as redirects or compatibility views
- Keep LLM-heavy generation on selected steps only
- Add pruning for low-signal topics before user-facing publication
