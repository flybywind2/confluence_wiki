# confluence_wiki

Confluence Data Center mirror 기반 markdown wiki 서비스입니다. 여러 Space를 markdown 파일로 동기화하고, FastAPI로 문서 화면과 graph view를 제공합니다.

## 주요 기능

- mirror URL 전용 읽기, prod URL 전용 원문 링크
- `.env` 기반 Confluence URL, ID, PASSWORD, SSL 검증 설정
- Space별 bootstrap pageId + 하위 페이지 위키 생성
- 전전일 기준 Space 전체 증분 동기화
- markdown 파일 저장 + SQLite 메타데이터 저장
- 복잡한 표는 HTML fallback
- 이미지 로컬 저장 + VLM 기반 한국어 설명
- Obsidian 스타일 graph view
- 외부 스케줄러용 CLI / 관리자 API

## 환경 변수

필수 키는 [`.env.example`](D:/Python/confluence_wiki/repo_clone/.worktrees/codex-confluence-wiki/.env.example) 를 기준으로 맞추면 됩니다.

중요 항목:

- `CONF_MIRROR_BASE_URL`
- `CONF_PROD_BASE_URL`
- `CONF_USERNAME`
- `CONF_PASSWORD`
- `CONF_VERIFY_SSL=false`
- `SYNC_RATE_LIMIT_PER_MINUTE=10`
- `DATABASE_URL`
- `WIKI_ROOT`
- `CACHE_ROOT`
- `LLM_BASE_URL`, `LLM_MODEL`
- `VLM_BASE_URL`, `VLM_MODEL`

## 설치

```bash
python -m pip install -e ".[dev]"
copy .env.example .env
```

## 실행

웹 서버:

```bash
python -m uvicorn app.main:app --reload
```

Bootstrap:

```bash
python -m app.cli bootstrap --space DEMO --page-id 123456
```

증분 동기화:

```bash
python -m app.cli sync --space DEMO
```

## 관리자 API

외부 스케줄러가 직접 호출할 경우:

- `POST /admin/bootstrap`
- `POST /admin/sync`

헤더:

```text
X-Admin-Token: <SYNC_ADMIN_TOKEN>
```

## 저장 구조

- 문서: `data/wiki/spaces/<SPACE_KEY>/pages/*.md`
- 이미지: `data/wiki/spaces/<SPACE_KEY>/assets/*`
- 그래프: `data/wiki/global/graph.json`
- DB: `data/db/app.db`

## 설계 문서

- [docs/plans/2026-04-06-confluence-wiki-design.md](D:/Python/confluence_wiki/repo_clone/.worktrees/codex-confluence-wiki/docs/plans/2026-04-06-confluence-wiki-design.md)
- [docs/plans/2026-04-06-confluence-wiki.md](D:/Python/confluence_wiki/repo_clone/.worktrees/codex-confluence-wiki/docs/plans/2026-04-06-confluence-wiki.md)
