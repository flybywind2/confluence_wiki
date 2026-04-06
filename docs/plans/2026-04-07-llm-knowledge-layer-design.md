# LLM Knowledge Layer Design

## Goal

Finish the remaining parts of the `llm-wiki` pattern by adding an LLM-maintained knowledge layer on top of the Confluence-derived page layer. The wiki should no longer be only a mirrored set of page snapshots; it should also accumulate synthesized entity, concept, and analysis pages, save useful question results back into the wiki, expose a lint/health-check artifact, enrich the catalog index, and ship a schema document that tells future agents how to maintain the wiki.

## Current Gap

The current system now has:

- Confluence page markdown
- per-page history snapshots
- append-only sync log
- per-space synthesis page
- graph view

But it is still missing the parts of the gist that make the wiki a compounding artifact:

- no knowledge page layer separate from raw mirrored pages
- no persistence of useful Q&A outputs as wiki documents
- no lint pass output
- index is a plain link list instead of a useful catalog
- no schema file such as `AGENTS.md`

## Approved Structure

Knowledge pages will live under:

```text
spaces/<SPACE_KEY>/knowledge/
  entities/
  concepts/
  analyses/
```

This keeps them separate from raw mirrored page snapshots while still living inside the same space-level wiki tree.

## Approaches

### 1. Recommended: DB-backed knowledge documents + markdown files

- add a `knowledge_documents` table
- keep each knowledge page as a markdown file under `knowledge/`
- route/search/index/assistant operate over both mirrored pages and knowledge pages
- `ask` may optionally persist an `analysis` page

This fits the current architecture best because the app already relies on SQLAlchemy for document discovery.

### 2. File-only knowledge documents

- create markdown files only
- discover them by directory walking at runtime

This is simpler at first, but it splits document discovery logic between DB-backed Confluence pages and file-scanned knowledge pages. That would make search, history, graph, and future migration harder.

## Data Model

Add `knowledge_documents`:

- `id`
- `space_id`
- `kind` (`entity`, `concept`, `analysis`, `lint`)
- `slug`
- `title`
- `markdown_path`
- `summary`
- `source_refs`
- `created_at`
- `updated_at`

`source_refs` can stay as plain text for portability. It only needs to be enough for frontmatter and rebuild workflows.

## Knowledge Generation Rules

### Entity pages

Generated from mirrored page content when the system sees repeated, important named terms. The first implementation should be conservative and deterministic:

- use headings, bold text, and repeated title-case or Korean noun phrases
- create only a small number of entity pages per space
- update existing entity pages instead of creating duplicates

### Concept pages

Generated from recurring themes across mirrored pages. For the first version, concept pages may be driven by synthesis and top repeated link targets rather than a fully open-ended extraction workflow.

### Analysis pages

Saved from user questions. The floating assistant remains conversational, but the user should be able to persist a useful answer as a wiki page under `knowledge/analyses/`.

Each analysis page should include:

- question
- scope
- answer
- cited source links
- saved time

## Lint Workflow

Add a lint operation that produces:

- `spaces/<SPACE_KEY>/knowledge/lint.md`

The first implementation should detect:

- orphan mirrored pages with no inbound wiki links
- orphan knowledge pages
- pages missing summaries
- spaces with no synthesis file
- pages whose current version lacks a history snapshot path

This is narrower than the full gist vision, but it is a real health-check pass and creates the right artifact.

## Indexing

Upgrade the index from a plain list to a catalog:

- mirrored pages grouped as `Pages`
- knowledge pages grouped as `Entities`, `Concepts`, `Analyses`, `Lint`
- each line includes wiki link plus summary
- optionally include updated time

The assistant should use this richer index as part of source selection.

## UI

### Space home

- expose links to synthesis and lint
- show recent analyses where available

### Knowledge pages

- knowledge pages render through the same `page.html` template family
- visual badge shows `entity`, `concept`, `analysis`, or `lint`

### Assistant modal

- add a `Save to Wiki` action after a successful answer
- user can choose `selected space` or `global` as before
- saved result becomes an analysis page under the selected space

## Schema Document

Add `AGENTS.md` at repo root with:

- wiki structure
- naming rules
- what counts as raw vs knowledge content
- ingest workflow
- ask workflow
- lint workflow
- index/log conventions

## Out of Scope

- full contradiction detection via NLI
- diffing and merge review UI for knowledge pages
- automatic multi-space global thesis pages
- autonomous background lint scheduling

## Testing

Add tests for:

- creating and routing knowledge docs
- saving assistant answers as analysis pages
- generating `lint.md`
- richer `index.md` content
- assistant source collection including knowledge docs

## Result

After this change, the project will finally have all major building blocks from the gist:

- raw page layer
- LLM-maintained knowledge layer
- append-only log
- useful catalog index
- schema document
- question results that can compound instead of disappearing into chat
