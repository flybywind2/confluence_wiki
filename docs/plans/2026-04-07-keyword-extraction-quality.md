# Keyword Extraction Quality Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve keyword page quality with title-first weighted extraction, DS domain normalization, and higher minimum keyword counts by document length.

**Architecture:** Keep deterministic keyword generation, but replace plain body frequency with weighted structural signals and a normalization layer. Use title seeds first, promote body tokens only when backed by structure, and guarantee a minimum number of keywords per document by length without allowing stopwords through.

**Tech Stack:** Python, FastAPI, SQLAlchemy, markdown file generation, pytest

---

### Task 1: Add failing regression tests for normalization and weighted extraction

**Files:**
- Modify: `D:/Python/confluence_wiki/repo_clone/tests/integration/test_end_to_end_sync.py`
- Modify: `D:/Python/confluence_wiki/repo_clone/tests/integration/test_demo_seed.py`

**Step 1: Write the failing test**

Add tests for:
- `삼성 DS` / `Device Solutions` -> `DS부문`
- no accidental `디스플레이` keyword without explicit source text
- weak titles like `주간 회의록` still yielding structural keywords
- minimum keyword count by long document length

**Step 2: Run test to verify it fails**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/integration/test_end_to_end_sync.py D:/Python/confluence_wiki/repo_clone/tests/integration/test_demo_seed.py -q`
Expected: FAIL because extraction is still body-frequency driven.

**Step 3: Write minimal implementation**

Implement only enough extraction changes to satisfy those cases.

**Step 4: Run test to verify it passes**

Run: `python -m pytest D:/Python/confluence_wiki/repo_clone/tests/integration/test_end_to_end_sync.py D:/Python/confluence_wiki/repo_clone/tests/integration/test_demo_seed.py -q`
Expected: PASS

### Task 2: Update keyword extraction internals

**Files:**
- Modify: `D:/Python/confluence_wiki/repo_clone/app/services/knowledge_service.py`

**Step 1: Write the failing test**

Use targeted tests from Task 1 as the contract.

**Step 2: Run test to verify it fails**

Run the same targeted tests and confirm RED.

**Step 3: Write minimal implementation**

Add:
- normalization dictionary
- title blacklist
- structural signal extraction
- weighted scores
- minimum keyword selection by length

**Step 4: Run test to verify it passes**

Run the targeted tests again.

### Task 3: Strengthen prompt guardrails

**Files:**
- Modify: `D:/Python/confluence_wiki/repo_clone/app/llm/text_client.py`

**Step 1: Write the failing test**

No direct LLM unit test required; use explicit deterministic helper tests where possible and then inspect prompt text in code.

**Step 2: Run verification for current state**

Confirm prompts do not yet include DS-specific guardrails.

**Step 3: Write minimal implementation**

Add prompt rules stating:
- `삼성 DS` means `DS부문`
- do not reinterpret it as display/business display unless the source explicitly says so

**Step 4: Run targeted tests**

Run the same integration tests to confirm no regressions.

### Task 4: Final verification

**Files:**
- Verify only

**Step 1: Run full suite**

Run: `python -m pytest -q`
Expected: all tests pass

**Step 2: Browser verification**

Check that:
- structural junk keywords are absent
- `DS부문` appears when relevant
- keyword count visibly increases on long documents

**Step 3: Commit**

```bash
git add .
git commit -m "feat: improve keyword extraction quality"
```
