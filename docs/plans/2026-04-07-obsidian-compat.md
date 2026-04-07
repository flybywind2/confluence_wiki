# Obsidian Compatibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 저장 markdown를 Obsidian 호환 형식으로 업그레이드하고, 웹 렌더러와 assistant 파서도 그 형식을 이해하게 만든다.

**Architecture:** Obsidian path/link helper를 도입하고, sync/index/knowledge/asset 저장 경로가 이를 사용한다. 렌더러는 vault-relative wikilink와 embed를 URL로 다시 매핑한다.

**Tech Stack:** Python, FastAPI, markdown-it, YAML frontmatter

---

### Task 1: 저장 포맷 테스트 추가

- `tests/services/test_assets.py`
- `tests/services/test_wiki_writer.py`
- `tests/core/test_markdown.py`

### Task 2: renderer/wikilink 구현

- `app/core/obsidian.py`
- `app/core/markdown.py`

### Task 3: sync/index/knowledge 저장 포맷 변경

- `app/services/assets.py`
- `app/services/sync_service.py`
- `app/services/index_builder.py`
- `app/services/knowledge_service.py`

### Task 4: assistant/parser 적응

- `app/services/wiki_qa.py`

### Task 5: prompt 강화

- `app/llm/text_client.py`

### Task 6: verify and docs

- `README.md`
- `python -m pytest -q`
