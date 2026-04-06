# Confluence Multi-Space Wiki Design

## Goal

Build a Python + FastAPI service that reads Confluence Data Center content from a mirror endpoint, converts selected spaces into a persistent markdown wiki, and serves that wiki through a user-facing web UI with NamuWiki-style readability and an Obsidian-style graph view.

## Confirmed Requirements

- Use Confluence Data Center REST APIs.
- Read operations must use the mirror URL only.
- Original document links shown to users must use the production URL.
- Confluence credentials and URLs must be managed in `.env`.
- Confluence SSL verification must be disabled through configuration.
- Mirror API usage is limited to `10 requests per minute`.
- Users can register one or more spaces.
- Each space can have a bootstrap `pageId`; initial wiki generation starts from that page and includes all descendants.
- Daily incremental sync must search the full space, not only the bootstrap subtree.
- Daily incremental sync window is `the day before yesterday, 00:00:00 through 23:59:59`.
- Output wiki must be markdown-file based.
- Tables must be parsed carefully, preserving complex structures safely.
- Images inside page bodies should be downloaded when possible, described with a VLM, and shown in the wiki when useful.
- LLM calls must use the provided OpenAI-compatible API style.
- VLM calls must use the provided OpenAI-compatible API style.
- Compatibility with OpenCode-style OpenAI APIs is required.
- The service must expose a web UI where users can browse content and choose which space to display.
- The UI must provide a graph view that combines Confluence parent-child links and wiki `[[links]]`.
- External schedulers should trigger syncs; scheduling must not live inside FastAPI.

## Architecture

The system is split into five layers.

1. `FastAPI app`
   - Renders markdown wiki pages.
   - Exposes search, graph, and admin trigger endpoints.
   - Lets the user choose a specific space or an all-spaces view.

2. `Sync worker`
   - Runs on demand from CLI or a protected HTTP endpoint.
   - Performs bootstrap sync and daily incremental sync.
   - Rebuilds affected wiki pages, indexes, and graph cache.

3. `Confluence integration`
   - Uses mirror base URL for every read call.
   - Uses configured username/password auth.
   - Applies `verify=False` according to `.env`.
   - Shares one rate limiter across page fetches, searches, attachments, and image downloads.

4. `Wiki store`
   - Saves generated markdown files and downloaded assets on disk.
   - Produces per-space indexes and global indexes.
   - Stores rendered graph data for fast UI loading.

5. `Metadata database`
   - Starts on SQLite.
   - Uses SQLAlchemy 2.x and Alembic from day one so the same models can migrate later to MySQL or PostgreSQL.
   - Stores sync state, page mappings, asset metadata, and link edges.

## Directory Layout

```text
D:\Python\confluence_wiki\
  app\
    api\
    clients\
    core\
    db\
    graph\
    llm\
    parser\
    services\
    templates\
    static\
  data\
    wiki\
      spaces\
        <SPACE_KEY>\
          pages\
          assets\
          index.md
          log.md
      global\
        index.md
        graph.json
    cache\
    db\
      app.db
  tests\
  docs\
    plans\
  .env
  .env.example
  pyproject.toml
```

## Data Model

The database should stay portable across SQLite, MySQL, and PostgreSQL. Avoid vendor-specific JSON features unless they are optional.

### `spaces`

- `id`
- `space_key`
- `name`
- `root_page_id`
- `enabled`
- `last_bootstrap_at`
- `last_incremental_at`
- `created_at`
- `updated_at`

### `pages`

- `id`
- `confluence_page_id`
- `space_id`
- `parent_confluence_page_id`
- `title`
- `slug`
- `prod_url`
- `status`
- `current_version`
- `created_at_remote`
- `updated_at_remote`
- `last_synced_at`

### `page_versions`

- `id`
- `page_id`
- `version_number`
- `body_hash`
- `source_excerpt_hash`
- `synced_at`

### `assets`

- `id`
- `page_id`
- `confluence_attachment_id`
- `filename`
- `mime_type`
- `local_path`
- `body_path`
- `is_image`
- `vlm_status`
- `vlm_summary`
- `downloaded_at`

### `page_links`

- `id`
- `source_page_id`
- `target_page_id`
- `target_title`
- `link_type`
- `created_at`

`link_type` values:

- `hierarchy`
- `wiki`

### `sync_runs`

- `id`
- `mode`
- `space_id`
- `started_at`
- `finished_at`
- `status`
- `processed_pages`
- `processed_assets`
- `error_message`

### `sync_cursors`

- `id`
- `space_id`
- `cursor_type`
- `cursor_value`
- `updated_at`

### `wiki_documents`

- `id`
- `page_id`
- `markdown_path`
- `summary`
- `index_line`
- `rendered_at`

## Configuration

Use `pydantic-settings` with `.env` as the primary source.

Example keys:

```env
APP_ENV=local
APP_HOST=0.0.0.0
APP_PORT=8000

CONF_MIRROR_BASE_URL=https://mirror.example.com/confluence
CONF_PROD_BASE_URL=https://prod.example.com/confluence
CONF_USERNAME=your_id
CONF_PASSWORD=your_password
CONF_VERIFY_SSL=false

SYNC_RATE_LIMIT_PER_MINUTE=10
SYNC_REQUEST_TIMEOUT_SECONDS=30
SYNC_ADMIN_TOKEN=change-me

OPENAI_API_KEY=api_key
LLM_BASE_URL=http://api.net:8000/v1
LLM_MODEL=QWEN3
LLM_DEP_TICKET=credential:TICKET-
LLM_SEND_SYSTEM_NAME=test
LLM_USER_ID=ID
LLM_USER_TYPE=AD_ID

VLM_BASE_URL=http://api.net/vl/v1
VLM_MODEL=QWEN3-VL
VLM_DEP_TICKET=credential:TICKET-
VLM_SEND_SYSTEM_NAME=test
VLM_USER_ID=ID
VLM_USER_TYPE=AD_ID

DATABASE_URL=sqlite:///./data/db/app.db
WIKI_ROOT=./data/wiki
CACHE_ROOT=./data/cache
```

## Sync Flow

### Bootstrap

1. Operator registers one or more spaces, each with a `space_key` and bootstrap `pageId`.
2. Service fetches the bootstrap page and its descendants from the mirror endpoint.
3. Service fetches page bodies, metadata, and attachments within the limiter budget.
4. Service parses Confluence storage content into markdown-safe content blocks.
5. Service writes markdown files, assets, index files, and graph data.
6. Service records page versions, sync run metadata, and link edges in the database.

### Daily Incremental

1. External scheduler calls a CLI command or protected HTTP endpoint once per day.
2. Service computes the `day before yesterday` time window in local time.
3. For each enabled space, service sends a CQL query over the full space.
4. Matching pages are fetched from the mirror endpoint and reprocessed.
5. Only changed pages and affected indexes/graph edges are rewritten.
6. Sync results are stored in `sync_runs`.

## Confluence API Rules

- Use mirror URL for:
  - page fetch
  - descendant fetch
  - CQL search
  - attachment metadata
  - attachment/image download
- Use production URL only for human-facing links embedded in the wiki UI.
- Use session-based auth with `username/password`.
- Set SSL verification from `.env`, currently `false`.
- Limit all outbound Confluence calls through one shared limiter set to `10/minute`.

## Markdown Generation Rules

Each page markdown file should contain:

- YAML frontmatter with source metadata.
- Human-readable title.
- Link to the original production page.
- Optional short summary.
- Parsed body content.
- Related page references.
- Embedded local images where available.

Suggested frontmatter:

```yaml
---
space_key: DEMO
page_id: "123456"
parent_page_id: "123455"
title: Example Page
slug: demo/example-page
source_url: https://prod.example.com/confluence/pages/viewpage.action?pageId=123456
updated_at: 2026-04-04T13:20:00+09:00
labels:
  - architecture
  - api
---
```

Internal cross-links should use a stable wiki path pattern:

```text
[[DEMO/example-page]]
```

## Table Parsing Strategy

Confluence tables cannot be flattened blindly.

### Simple tables

When the table has a clean header row and no merged cells:

- convert to markdown table
- preserve inline links and text formatting where possible

### Complex tables

When the table includes `rowspan`, `colspan`, nested blocks, macros, or panel-heavy markup:

- preserve as semantic HTML table inside markdown
- keep cell text normalized
- retain links

### Fallback rule

If the converter cannot prove that markdown output is structurally safe, keep the table as HTML.

## Image and Attachment Strategy

- Detect embedded images and file attachments in Confluence storage.
- Download supported files to `data/wiki/spaces/<SPACE_KEY>/assets/`.
- Replace wiki body references with local paths when possible.
- For images, call the VLM and generate a Korean description.
- Save the VLM result in both:
  - `assets.vlm_summary` in the database
  - markdown output near the image, preferably as caption or collapsible note
- If an image is central to understanding the page, show it inline in the wiki.

## LLM and VLM Integration

Wrap both provided APIs behind adapters that expose one common interface to the application.

### Text LLM usage

Use the provided OpenAI-compatible client style for:

- summary generation
- related-link suggestion
- optional normalization tasks

### Vision model usage

Use the provided OpenAI-compatible VLM style for:

- image caption generation
- diagram/photo explanation for wiki text enrichment

Compatibility rules:

- keep message payloads OpenAI-style
- isolate vendor headers in the adapter layer
- avoid leaking provider-specific details into business logic

## Graph View

The graph view should expose both structural and semantic relationships.

### Nodes

- one node per wiki page
- include title, space key, slug, and last updated metadata

### Edges

- `hierarchy`: Confluence parent-child relation
- `wiki`: markdown `[[link]]` relation

### UI behavior

- force-directed graph
- color by space
- edge style by link type
- filter by space
- click node to open wiki page
- support all-spaces and single-space modes

## FastAPI Surface

### User-facing routes

- `/`
- `/spaces/{space_key}`
- `/spaces/{space_key}/pages/{slug:path}`
- `/search`
- `/graph`

### API routes

- `/api/spaces`
- `/api/search`
- `/api/graph`
- `/api/pages/{space_key}/{slug}`

### Admin routes or CLI

- `POST /admin/bootstrap`
- `POST /admin/sync`
- `python -m app.cli bootstrap --space DEMO --page-id 123456`
- `python -m app.cli sync --mode incremental`

Admin access should be protected by a token from `.env`.

## UI Direction

The UI should be document-first, not dashboard-first.

- Wiki pages should feel closer to NamuWiki than to an admin panel.
- Typography should prioritize reading comfort.
- Space selection should be persistent and obvious.
- Graph view should feel like a research navigation aid, not a toy widget.

## Testing Strategy

Use TDD during implementation.

Priority test areas:

1. configuration loading from `.env`
2. Confluence client auth, URL routing, and SSL settings
3. rate limiting behavior
4. CQL time-window generation
5. Confluence storage parsing
6. table conversion fallback behavior
7. image download and VLM caption flow
8. markdown writing and index/log generation
9. graph extraction and filtering
10. FastAPI page rendering and API responses

## Risks and Mitigations

- `10/minute rate limit`
  - central limiter, queueing, small page batches
- `complex Confluence markup`
  - HTML fallback for unsupported content
- `image explosion`
  - prioritize inline images first, optionally skip large low-value assets
- `future DB migration`
  - SQLAlchemy models, Alembic, DB-neutral schema choices
- `SSL verification disabled`
  - isolate this to Confluence client config only, do not disable globally

## Notes

- There is no git repository in the current workspace yet, so the design document cannot be committed at this stage.
- The next step is to create a detailed implementation plan under `docs/plans/`.
