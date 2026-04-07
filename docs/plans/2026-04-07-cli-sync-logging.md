# CLI Sync Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** CLI bootstrap/sync 실행 시 기본 진행 로그와 선택적 verbose 로그를 출력한다.

**Architecture:** `app.cli` 가 `logging.basicConfig` 를 통해 루트 로거를 설정하고, `SyncService` 가 표준 logger 로 진행 상황을 기록한다. 기본 레벨은 `INFO`, `--verbose` 는 `DEBUG` 로 동작한다.

**Tech Stack:** Python 3.10+, argparse, logging, pytest

---

### Task 1: CLI 옵션 테스트 추가

**Files:**
- Create: `tests/test_cli.py`
- Modify: `app/cli.py`

**Step 1: Write the failing test**

```python
def test_build_parser_accepts_verbose_for_bootstrap():
    parser = build_parser()
    args = parser.parse_args(["bootstrap", "--space", "DEMO", "--page-id", "1", "--verbose"])
    assert args.verbose is True
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -q`
Expected: FAIL because `--verbose` is unknown.

**Step 3: Write minimal implementation**

Add `--verbose` to both `bootstrap` and `sync`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -q`
Expected: PASS

### Task 2: SyncService 로그 테스트 추가

**Files:**
- Modify: `tests/integration/test_end_to_end_sync.py`
- Modify: `app/services/sync_service.py`

**Step 1: Write the failing test**

```python
def test_incremental_sync_emits_progress_logs(..., caplog):
    caplog.set_level("INFO")
    service.run_incremental(space_key="DEMO")
    assert "sync start" in caplog.text
    assert "processing page 1/2" in caplog.text
    assert "sync complete" in caplog.text
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_end_to_end_sync.py -q`
Expected: FAIL because no logs are emitted.

**Step 3: Write minimal implementation**

Use `logging.getLogger(__name__)` and add `INFO` log calls around sync lifecycle.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_end_to_end_sync.py -q`
Expected: PASS

### Task 3: Verbose debug 로그 구현

**Files:**
- Modify: `app/services/sync_service.py`
- Modify: `tests/integration/test_end_to_end_sync.py`

**Step 1: Write the failing test**

```python
def test_incremental_sync_emits_debug_asset_logs(..., caplog):
    caplog.set_level("DEBUG")
    service.run_incremental(space_key="DEMO")
    assert "downloading attachment" in caplog.text
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_end_to_end_sync.py -q`
Expected: FAIL because no debug logs exist.

**Step 3: Write minimal implementation**

Add `DEBUG` logs for attachment download, image replacement, and view rebuild.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/integration/test_end_to_end_sync.py -q`
Expected: PASS

### Task 4: CLI logging bootstrap

**Files:**
- Modify: `app/cli.py`
- Modify: `README.md`

**Step 1: Implement logging setup**

Configure `logging.basicConfig` in `main()` using `INFO` or `DEBUG`.

**Step 2: Update docs**

Explain default progress logs and `--verbose` detailed logs in README.

**Step 3: Verify**

Run:
- `python -m pytest tests/test_cli.py tests/integration/test_end_to_end_sync.py -q`
- `python -m pytest -q`

Expected: PASS
