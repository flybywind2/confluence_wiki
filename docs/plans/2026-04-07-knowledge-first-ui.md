# Knowledge-First UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** UI를 knowledge-first 위키로 바꾸고, raw page를 fact-card 입력으로 사용해 concept/synthesis 문서를 더 강하게 생성한다.

**Architecture:** `KnowledgeService` 가 raw page를 fact-card로 정리한 뒤 concept/synthesis 문서를 만든다. `routes` 와 `search` 는 knowledge 문서만 기본 노출하고, `WikiQAService` 는 knowledge 우선 검색 후 raw fallback을 사용한다.

**Tech Stack:** FastAPI, SQLAlchemy, markdown files, OpenAI-compatible LLM API, pytest

---

### Task 1: 홈/검색 노출 테스트 작성

**Files:**
- Modify: `tests/api/test_api_endpoints.py`

**Step 1: Write failing tests**

- 홈에서 raw page title이 보이지 않고 knowledge title만 보이는지 테스트
- 검색에서 raw page 대신 knowledge 결과만 기본 노출하는지 테스트

**Step 2: Run tests and verify failure**

Run: `python -m pytest tests/api/test_api_endpoints.py -q`

### Task 2: concept 생성 테스트 작성

**Files:**
- Modify: `tests/integration/test_end_to_end_sync.py`

**Step 1: Write failing tests**

- sync 후 `knowledge/concepts/` 아래에 `core-topics` 외 추가 concept 문서가 생성되는지 테스트
- concept 문서가 여러 raw page 링크를 포함하는지 테스트

**Step 2: Run tests and verify failure**

Run: `python -m pytest tests/integration/test_end_to_end_sync.py -q`

### Task 3: fact-card / concept synthesis 구현

**Files:**
- Modify: `app/services/knowledge_service.py`
- Modify: `app/llm/text_client.py`

**Step 1: Add prompts**

- `summarize_page_fact_card()`
- `synthesize_concepts()`
- `build_space_synthesis()`

**Step 2: Generate concept docs**

- raw page summaries, links, update times를 사용해 topic clusters 구성
- `concept` 문서를 여러 개 만들고 `entity`는 내부용만 유지

### Task 4: routes/templates/search behavior 변경

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/templates/index.html`
- Modify: `app/templates/page.html`

**Step 1: Change exposure**

- 홈/space 홈/검색은 knowledge만 기본 노출
- raw page route는 유지
- knowledge 상세에 raw 근거 링크를 노출

### Task 5: assistant knowledge-first 변경

**Files:**
- Modify: `app/services/wiki_qa.py`

**Step 1: Prefer knowledge docs**

- ranking에서 knowledge를 우선
- fallback으로만 raw 사용

### Task 6: docs and verification

**Files:**
- Modify: `README.md`

**Step 1: Verify**

Run:
- `python -m pytest tests/api/test_api_endpoints.py tests/integration/test_end_to_end_sync.py -q`
- `python -m pytest -q`
