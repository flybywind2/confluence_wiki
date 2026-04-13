# SQLite Scale Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** SQLite를 유지한 상태에서 raw/knowledge 문서 수 증가에 따른 병목을 줄이고 운영 가능한 최대 문서 수를 늘린다.

**Architecture:** 저장 구조는 SQLite + markdown wiki를 유지하되, 검색은 FTS5로 이동하고, knowledge/lint/index/graph는 부분 갱신을 우선한다. 쓰기 작업은 단일 queue로 직렬화하고, heavy maintenance는 online sync 경로에서 제거한다.

**Tech Stack:** SQLite, SQLAlchemy, Alembic, FTS5, FastAPI

---

### Task 1: Add SQLite Integrity Constraints

**Files:**
- Modify: `D:\Python\confluence_wiki\repo_clone\app\db\models.py`
- Create: `D:\Python\confluence_wiki\repo_clone\alembic\versions\20260413_000005_sqlite_integrity_indexes.py`
- Test: `D:\Python\confluence_wiki\repo_clone\tests\db\test_migrations.py`

**Steps:**
1. Add failing migration assertions for composite unique constraints.
2. Run `python -m pytest tests\db\test_migrations.py -q`.
3. Implement the migration and matching model metadata.
4. Re-run the test.
5. Commit.

### Task 2: Introduce Raw Chunk Storage and FTS5

**Files:**
- Modify: `D:\Python\confluence_wiki\repo_clone\app\db\models.py`
- Create: `D:\Python\confluence_wiki\repo_clone\alembic\versions\20260413_000006_raw_page_chunks_fts.py`
- Create: `D:\Python\confluence_wiki\repo_clone\app\services\chunk_index.py`
- Test: `D:\Python\confluence_wiki\repo_clone\tests\services\test_chunk_index.py`

**Steps:**
1. Write failing tests for chunk insert/update and FTS query.
2. Run `python -m pytest tests\services\test_chunk_index.py -q`.
3. Implement minimal chunk storage and FTS5 refresh.
4. Re-run tests.
5. Commit.

### Task 3: Rewire Query Search to FTS5 Candidates

**Files:**
- Modify: `D:\Python\confluence_wiki\repo_clone\app\services\knowledge_service.py`
- Modify: `D:\Python\confluence_wiki\repo_clone\app\services\wiki_qa.py`
- Test: `D:\Python\confluence_wiki\repo_clone\tests\services\test_knowledge_service.py`
- Test: `D:\Python\confluence_wiki\repo_clone\tests\services\test_wiki_qa.py`

**Steps:**
1. Add failing tests for FTS-backed candidate selection.
2. Run the targeted tests.
3. Implement minimal FTS5 candidate lookup before file fallback.
4. Re-run tests.
5. Commit.

### Task 4: Expand Partial Rebuild to Lint and Index

**Files:**
- Modify: `D:\Python\confluence_wiki\repo_clone\app\services\sync_service.py`
- Modify: `D:\Python\confluence_wiki\repo_clone\app\services\lint_service.py`
- Modify: `D:\Python\confluence_wiki\repo_clone\app\services\index_builder.py`
- Test: `D:\Python\confluence_wiki\repo_clone\tests\services\test_sync_service.py`
- Test: `D:\Python\confluence_wiki\repo_clone\tests\services\test_lint_service.py`

**Steps:**
1. Add failing tests for partial lint/index rebuild.
2. Run the targeted tests.
3. Implement minimal touched-page rebuild wiring.
4. Re-run tests.
5. Commit.

### Task 5: Document SQLite Operations Limits

**Files:**
- Modify: `D:\Python\confluence_wiki\repo_clone\README.md`
- Create: `D:\Python\confluence_wiki\repo_clone\sqlite_scale.md`

**Steps:**
1. Document safe range, FTS5 requirement, nightly maintenance, and PostgreSQL cutoff.
2. Review links and examples.
3. Commit.
