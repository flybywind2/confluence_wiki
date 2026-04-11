# Confluence HTML Parser Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve Confluence storage HTML parsing so raw wiki markdown preserves structure needed for better knowledge generation.

**Architecture:** Replace the current flat pass in `app/parser/storage.py` with a block-oriented Confluence parser. Keep inline placeholder behavior, reuse the existing table renderer, and add explicit macro rendering for common Confluence blocks.

**Tech Stack:** Python, BeautifulSoup/selectolax-style block parsing, pytest

---

### Task 1: Add failing parser tests

**Files:**
- Create: `tests/parser/test_storage.py`
- Modify: `tests/fixtures/*.html` if needed

**Step 1: Write the failing test**

- Add tests for:
  - Confluence page link conversion
  - nested list rendering
  - `info` macro to callout
  - `expand` macro to collapsible/callout markdown
  - code macro to fenced block
  - attachment image placeholder

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/parser/test_storage.py -q`

**Step 3: Commit**

- Commit after parser behavior passes, not before.

### Task 2: Refactor storage parser

**Files:**
- Modify: `app/parser/storage.py`

**Step 1: Add block rendering helpers**

- Split current logic into:
  - block traversal
  - inline rendering
  - macro rendering
  - list rendering

**Step 2: Implement common Confluence macro support**

- Handle:
  - `ac:structured-macro` `info/note/warning/tip`
  - `expand`
  - `code`

**Step 3: Preserve nested structure**

- Render child blocks recursively instead of flattening everything to plain text.

### Task 3: Verify table/image compatibility

**Files:**
- Modify: `app/parser/storage.py`
- Test: `tests/parser/test_tables.py`

**Step 1: Keep table behavior unchanged**

- Ensure `render_table_block()` is still used for `<table>`

**Step 2: Keep image placeholder behavior unchanged**

- Ensure `ac:image`, `ri:attachment`, and external `img` handling still produce placeholders used later by sync

### Task 4: Run targeted verification

**Files:**
- Test: `tests/parser/test_storage.py`
- Test: `tests/parser/test_tables.py`
- Test: `tests/integration/test_end_to_end_sync.py`

**Step 1: Run parser tests**

Run: `python -m pytest tests/parser/test_storage.py tests/parser/test_tables.py -q`

**Step 2: Run relevant integration tests**

Run: `python -m pytest tests/integration/test_end_to_end_sync.py -k "table or image or markdown" -q`

### Task 5: Update dependency docs if needed

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md` if parser dependency or behavior changes

**Step 1: Add parser dependency only if actually used**

- Keep changes minimal

**Step 2: Document behavior briefly**

- Mention that common Confluence macros are preserved better in markdown output
