# Persistent LLM Wiki Design

## Goal

Extend the current Confluence-to-markdown wiki so it behaves more like the pattern described in Karpathy's `llm-wiki` gist: the system should preserve page history, maintain append-only operational logs, and keep cumulative synthesis pages that evolve as new Confluence revisions arrive.

## Current Gap

The current implementation materializes Confluence pages into markdown and serves a readable wiki, but it is still a latest-snapshot system:

- page markdown files are overwritten on each sync
- `page_versions` only stores hashes and sync timestamps
- `log.md` is rebuilt from recent pages instead of append-only journaling
- no persistent per-space synthesis page exists
- no UI exists for inspecting page revision history

That means the project already has a file-based wiki, but not yet a persistent, compounding wiki artifact.

## Approved Scope

This change adds four capabilities:

1. Persistent page revision snapshots
   - Every synced Confluence version gets its own markdown snapshot on disk.
   - The latest wiki page remains at `spaces/<SPACE>/pages/<slug>.md`.
   - Historical snapshots live at `spaces/<SPACE>/history/<slug>/v0001.md` and so on.

2. Append-only space log
   - `spaces/<SPACE>/log.md` becomes a chronological journal.
   - Sync runs append entries instead of rewriting the file.
   - Entries capture the operation type, time window, and affected wiki pages.

3. Space synthesis pages
   - Each space gets `spaces/<SPACE>/synthesis.md`.
   - The file is regenerated from current wiki summaries and recent log context.
   - It acts as the cumulative overview page for the space.

4. History-aware UI
   - Page detail shows history metadata and linked prior versions.
   - A dedicated history view lists available revisions and lets the user read old markdown snapshots.

## Storage Model

### Markdown layout

```text
data/wiki/
  spaces/
    <SPACE_KEY>/
      pages/
        <slug>.md
      history/
        <slug>/
          v0001.md
          v0002.md
      index.md
      log.md
      synthesis.md
```

### Database changes

The project already has `PageVersion`. It should become a real revision record.

Add to `page_versions`:

- `markdown_path`
- `summary`
- `source_updated_at`
- `created_at`

Keep:

- `version_number`
- `body_hash`
- `source_excerpt_hash`
- `synced_at`

This stays portable across SQLite, MySQL, and PostgreSQL because all new columns are standard scalar types.

## Sync Behavior

### Page sync

For each fetched Confluence page:

1. Convert storage body to markdown.
2. Write the latest page file.
3. Upsert `PageVersion`.
4. If the version is new, write a history snapshot file.
5. Refresh page summary and page links.

If the version already exists, the history snapshot should not be duplicated.

### Append-only log

Each successful bootstrap or incremental sync appends a block such as:

```markdown
## [2026-04-07 03:10:12+09:00] sync | DEMO | incremental
- window: 2026-04-05 00:00:00+09:00 ~ 2026-04-05 23:59:59+09:00
- pages: [[DEMO/demo-home-9001]], [[DEMO/sync-runbook-9003]]
```

This log is file-first and human-readable. `sync_runs` remains the machine-oriented source for operational state.

### Synthesis page

Each synthesis file should include:

- space title
- last generated time
- current high-level summary
- key pages
- recent changes
- open questions or gaps

The first implementation should derive synthesis from current page summaries and recent log entries. It does not need a separate LLM workflow beyond the existing text client.

## UI Changes

### Space home

- Add a prominent `Synthesis` entry.
- Keep recent updates, but source them from append-only log context where possible.

### Page detail

- Add a history rail or section with:
  - current version
  - remote updated time
  - version list
  - links to historical snapshots

### History page

- New route renders a specific version snapshot.
- The page should clearly state it is a historical revision and link back to the latest document.

## Out of Scope

- automatic saving of user Q&A answers as new analysis pages
- cross-space synthesis pages
- diff visualization between revisions
- editing or rollback from the UI

## Testing

Add coverage for:

- snapshot file creation on first sync
- no duplicate snapshot file on re-sync of same version
- append-only `log.md`
- `synthesis.md` generation
- history route rendering
- page detail exposing revision links

## Result

After this change, the wiki stops being only a view over current Confluence content. It becomes a persistent knowledge artifact with file-backed revision history, operational memory, and cumulative space-level synthesis, which is materially closer to the `llm-wiki` model.
