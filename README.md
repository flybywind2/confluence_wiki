# confluence_wiki

Confluence Data Center mirror 기반 markdown wiki 서비스입니다. 여러 Space를 markdown 파일로 동기화하고, FastAPI로 문서 화면과 graph view를 제공합니다.

## 주요 기능

- mirror URL 전용 읽기, prod URL 전용 원문 링크
- `.env` 기반 Confluence URL, ID, PASSWORD, SSL 검증 설정
- Space별 bootstrap pageId + 하위 페이지 위키 생성
- 전전일 기준 Space 전체 증분 동기화
- markdown 파일 저장 + SQLite 메타데이터 저장
- 문서별 history snapshot 저장
- append-only `log.md` 운영 로그
- space별 `synthesis.md` 누적 요약 페이지
- 복잡한 표는 HTML fallback
- 이미지 로컬 저장 + VLM 기반 한국어 설명
- Obsidian 스타일 graph view
- 우측 하단 플로팅 버튼 기반 Wiki Q&A 모달
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

`.env` 에서는 최소한 아래 값을 먼저 채워야 합니다.

- `CONF_MIRROR_BASE_URL`
- `CONF_PROD_BASE_URL`
- `CONF_USERNAME`
- `CONF_PASSWORD`
- `CONF_VERIFY_SSL=false`
- `SYNC_ADMIN_TOKEN`
- `DATABASE_URL`
- `WIKI_ROOT`
- `CACHE_ROOT`

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

데모 시드:

```bash
python -m app.demo_seed
```

샘플 markdown 원본은 `data/demo_seed/pages/` 아래에 있고, 시드 실행 시 `WIKI_ROOT`와 DB 메타데이터가 함께 채워집니다.

## 운영 순서

운영에서는 아래 순서를 권장합니다.

1. `.env` 를 채웁니다.
2. 기존 DB를 쓰고 있다면 migration 을 먼저 실행합니다.
3. Space별로 최초 1회 bootstrap 을 실행합니다.
4. 웹 서버를 상시 실행합니다.
5. 외부 스케줄러가 매일 `sync` 를 호출하게 붙입니다.

예시:

```bash
alembic upgrade head
python -m app.cli bootstrap --space DEMO --page-id 123456
python -m app.cli bootstrap --space ARCH --page-id 456789
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`sync` 는 내부적으로 항상 `전전일 00:00 ~ 23:59` 기준의 증분 동기화를 수행합니다.

## 외부 스케줄러 연동

권장 원칙:

- 여러 Space를 동시에 돌리지 않습니다.
- mirror 제한이 `10회/분` 이므로 Space 간에는 여유를 두고 순차 실행합니다.
- 최초 bootstrap 은 수동 또는 별도 운영 작업으로 처리하고, 일일 작업은 `sync` 만 스케줄링합니다.

두 가지 방식 중 하나를 쓰면 됩니다.

### 1. 같은 서버에서 CLI 호출

웹 서버와 같은 서버에서 스케줄러가 돈다면 이 방식이 가장 단순합니다.

예제 스크립트:

- [scripts/scheduler/invoke_sync_cli.ps1](D:/Python/confluence_wiki/repo_clone/.worktrees/codex-confluence-wiki/scripts/scheduler/invoke_sync_cli.ps1)

사용 예시:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scheduler\invoke_sync_cli.ps1 `
  -Spaces "DEMO,ARCH" `
  -PythonExe python `
  -PauseSeconds 75
```

동작:

- `DEMO` sync 실행
- `75초` 대기
- `ARCH` sync 실행

### 2. 별도 서버에서 HTTP admin API 호출

스케줄러가 다른 서버에 있거나, 중앙 배치 서버에서 호출할 때 적합합니다.

예제 스크립트:

- [scripts/scheduler/invoke_sync_http.ps1](D:/Python/confluence_wiki/repo_clone/.worktrees/codex-confluence-wiki/scripts/scheduler/invoke_sync_http.ps1)

사용 예시:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scheduler\invoke_sync_http.ps1 `
  -BaseUrl http://wiki-host:8000 `
  -AdminToken change-me `
  -Spaces "DEMO,ARCH" `
  -PauseSeconds 75
```

직접 호출 예시:

```bash
curl -X POST http://wiki-host:8000/admin/sync \
  -H "X-Admin-Token: change-me" \
  -H "Content-Type: application/json" \
  -d "{\"space\":\"DEMO\"}"
```

## Windows 작업 스케줄러 예시

Windows 작업 스케줄러에서 하루 1회 새벽 실행 예시는 아래처럼 잡으면 됩니다.

권장:

- `DEMO`: 매일 03:10
- `ARCH`: 매일 03:12 또는 03:15

같은 작업에 여러 space를 넣고 싶다면 CLI 스크립트를 사용하고, 한 작업에서 순차 실행되게 두는 편이 안전합니다.

작업 등록 예시:

```powershell
schtasks /Create /F /SC DAILY /ST 03:10 /TN "ConfluenceWikiSync" `
  /TR "powershell -ExecutionPolicy Bypass -File D:\Python\confluence_wiki\repo_clone\.worktrees\codex-confluence-wiki\scripts\scheduler\invoke_sync_cli.ps1 -Spaces ""DEMO,ARCH"" -PythonExe python -PauseSeconds 75"
```

이미 웹 서버가 떠 있고, 배치 서버에서 HTTP로만 쏘고 싶다면:

```powershell
schtasks /Create /F /SC DAILY /ST 03:10 /TN "ConfluenceWikiSyncHttp" `
  /TR "powershell -ExecutionPolicy Bypass -File D:\Python\confluence_wiki\repo_clone\.worktrees\codex-confluence-wiki\scripts\scheduler\invoke_sync_http.ps1 -BaseUrl http://wiki-host:8000 -AdminToken change-me -Spaces ""DEMO,ARCH"" -PauseSeconds 75"
```

## Linux cron 예시

Linux 에서 로컬 CLI 방식으로 붙일 경우:

```cron
10 3 * * * cd /opt/confluence_wiki && /usr/bin/pwsh -File ./scripts/scheduler/invoke_sync_cli.ps1 -Spaces "DEMO,ARCH" -PythonExe python3 -PauseSeconds 75 >> /var/log/confluence_wiki_sync.log 2>&1
```

HTTP 방식이라면:

```cron
10 3 * * * /usr/bin/pwsh -File /opt/confluence_wiki/scripts/scheduler/invoke_sync_http.ps1 -BaseUrl http://wiki-host:8000 -AdminToken change-me -Spaces "DEMO,ARCH" -PauseSeconds 75 >> /var/log/confluence_wiki_sync.log 2>&1
```

## 관리자 API

외부 스케줄러가 직접 호출할 경우:

- `POST /admin/bootstrap`
- `POST /admin/sync`

헤더:

```text
X-Admin-Token: <SYNC_ADMIN_TOKEN>
```

Payload 예시:

```json
{"space":"DEMO"}
```

## 저장 구조

- 문서: `data/wiki/spaces/<SPACE_KEY>/pages/*.md`
- 문서 이력: `data/wiki/spaces/<SPACE_KEY>/history/<slug>/v0001.md`
- space 누적 요약: `data/wiki/spaces/<SPACE_KEY>/synthesis.md`
- space 운영 로그: `data/wiki/spaces/<SPACE_KEY>/log.md`
- 이미지: `data/wiki/spaces/<SPACE_KEY>/assets/*`
- 그래프: `data/wiki/global/graph.json`
- DB: `data/db/app.db`

## 화면

- `문서 홈`: Space별 최근 문서와 synthesis 링크
- `문서 상세`: 원문 링크, 현재 버전, 최근 history 링크
- `문서 이력`: 버전 목록과 과거 snapshot 조회
- `Synthesis`: Space별 누적 요약 페이지
- `Graph View`: 계층 링크 + 위키 링크 동시 시각화

## 설계 문서

- [docs/plans/2026-04-06-confluence-wiki-design.md](D:/Python/confluence_wiki/repo_clone/.worktrees/codex-confluence-wiki/docs/plans/2026-04-06-confluence-wiki-design.md)
- [docs/plans/2026-04-06-confluence-wiki.md](D:/Python/confluence_wiki/repo_clone/.worktrees/codex-confluence-wiki/docs/plans/2026-04-06-confluence-wiki.md)
