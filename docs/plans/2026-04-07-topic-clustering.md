# Topic Clustering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** topic cluster 품질을 높이고, knowledge graph 및 facet 기반 탐색 UI를 추가한다.

**Architecture:** raw page -> fact card -> cluster seed -> LLM synthesis 흐름을 만들고, 이 결과를 concept 문서와 knowledge graph JSON에 반영한다. 홈/검색/graph는 facet filter를 사용해 같은 knowledge layer를 탐색한다.

**Tech Stack:** FastAPI, SQLAlchemy, markdown files, OpenAI-compatible LLM API, pytest

---

### Task 1: clustered concept tests

- `tests/integration/test_end_to_end_sync.py`
- cluster 문서가 대표 문서/남은 질문 섹션을 가지는지 테스트

### Task 2: knowledge graph tests

- `tests/api/test_api_endpoints.py`
- knowledge graph 노드/edge 타입을 확인

### Task 3: facet UX tests

- `tests/api/test_pages.py`
- 홈/검색/graph에서 facet filter 적용 결과를 검증

### Task 4: clustering implementation

- `app/services/knowledge_service.py`
- `app/llm/text_client.py`

### Task 5: knowledge graph implementation

- `app/services/sync_service.py`
- `app/graph/builder.py`
- `app/api/routes.py`

### Task 6: facet UI implementation

- `app/templates/index.html`
- `app/templates/graph.html`
- `app/api/routes.py`

### Task 7: verify and docs

- `README.md`
- `python -m pytest -q`
