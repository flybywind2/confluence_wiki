# confluence_wiki

Confluence Data Center mirror 기반 markdown wiki 서비스입니다. 여러 Space를 markdown 파일로 동기화하고, FastAPI로 문서 화면과 graph view를 제공합니다.

지원 Python 버전은 `3.10.11+` 입니다.

## 주요 기능

- mirror URL 전용 읽기, prod URL 전용 원문 링크
- `.env` 기반 Confluence URL, ID, PASSWORD, SSL 검증 설정
- Space별 bootstrap pageId + 하위 페이지 위키 생성
- 전전일 기준 Space 전체 증분 동기화
- markdown 파일 저장 + SQLite 메타데이터 저장
- 문서별 history snapshot 저장
- append-only `log.md` 운영 로그
- space별 `synthesis.md` 누적 요약 페이지
- `knowledge/entities`, `knowledge/concepts`, `knowledge/analyses`, `knowledge/lint` 지식 레이어
- 기본 UI는 `concept`, `analysis`, `lint`, `synthesis` 중심의 knowledge-first 노출
- raw Confluence page는 내부 근거와 direct URL용으로 유지
- 복잡한 표는 HTML fallback
- 이미지 로컬 저장 + VLM 기반 한국어 설명
- Obsidian 스타일 graph view
- 우측 하단 플로팅 버튼 기반 Wiki Q&A 모달
- assistant 답변을 분석 문서로 저장하고 재검색 근거로 재사용
- 외부 스케줄러용 CLI / 관리자 API

## LLM Wiki 구조

이 프로젝트는 [karpathy의 llm-wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 패턴을 Confluence Data Center에 맞게 구현한 형태입니다.

- raw source: mirror에서 읽는 Confluence 원문
- wiki: markdown 파일 기반 영속 위키
- schema: [AGENTS.md](./AGENTS.md)

질문 응답도 일회성 채팅으로 끝내지 않고 `knowledge/analyses/` 아래 markdown로 저장해 다시 위키의 일부로 관리합니다. 사용자가 기본 UI에서 보는 것은 raw page 목록이 아니라 knowledge 문서 계층입니다.

## 환경 변수

필수 키는 [`.env.example`](./.env.example) 를 기준으로 맞추면 됩니다.

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

Windows에서 Python 3.10.11을 명시적으로 쓰려면 예를 들어 아래처럼 실행하면 됩니다.

```powershell
py -3.10 -m pip install -e ".[dev]"
py -3.10 -m uvicorn app.main:app --reload
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

## CLI 로그와 진행 상황

현재 `python -m app.cli bootstrap ...` 과 `python -m app.cli sync ...` 는 기본적으로 진행 로그를 터미널에 출력합니다.

기본 실행에서는 `INFO` 레벨 로그가 출력됩니다.

- 시작: mode, space, root page id 또는 증분 대상 페이지 수
- 진행: 현재 페이지 `n/N`, page id, title
- 완료: 처리한 page 수, asset 수

상세 로그가 필요하면 `--verbose` 를 붙이면 됩니다. 이 경우 `DEBUG` 레벨 로그가 함께 출력됩니다.

- attachment 다운로드 시작/완료
- 본문 이미지 placeholder 치환
- materialized view 재빌드

운영 중 확인 가능한 위치는 아래와 같습니다.

- `data/wiki/spaces/<SPACE_KEY>/log.md`
  - 각 sync가 끝난 뒤 append-only 형태로 결과가 기록됩니다.
- DB의 `sync_runs` 테이블
  - `mode`, `status`, `processed_pages`, `processed_assets`, `finished_at` 같은 실행 메타데이터를 확인할 수 있습니다.
- 외부 스케줄러 로그
  - PowerShell, cron, 작업 스케줄러에서 실행 종료 코드와 예외 traceback을 수집할 수 있습니다.

예시:

```bash
python -m app.cli bootstrap --space DEMO --page-id 123456 --verbose
python -m app.cli sync --space DEMO --verbose
```

운영 점검은 `터미널 진행 로그 + log.md + sync_runs` 를 함께 보는 구성이 적절합니다.

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

- [scripts/scheduler/invoke_sync_cli.ps1](./scripts/scheduler/invoke_sync_cli.ps1)

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

- [scripts/scheduler/invoke_sync_http.ps1](./scripts/scheduler/invoke_sync_http.ps1)

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
  /TR "powershell -ExecutionPolicy Bypass -File D:\Python\confluence_wiki\repo_clone\scripts\scheduler\invoke_sync_cli.ps1 -Spaces ""DEMO,ARCH"" -PythonExe python -PauseSeconds 75"
```

이미 웹 서버가 떠 있고, 배치 서버에서 HTTP로만 쏘고 싶다면:

```powershell
schtasks /Create /F /SC DAILY /ST 03:10 /TN "ConfluenceWikiSyncHttp" `
  /TR "powershell -ExecutionPolicy Bypass -File D:\Python\confluence_wiki\repo_clone\scripts\scheduler\invoke_sync_http.ps1 -BaseUrl http://wiki-host:8000 -AdminToken change-me -Spaces ""DEMO,ARCH"" -PauseSeconds 75"
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
- 지식 문서:
  - `data/wiki/spaces/<SPACE_KEY>/knowledge/entities/*.md`
  - `data/wiki/spaces/<SPACE_KEY>/knowledge/concepts/*.md`
  - `data/wiki/spaces/<SPACE_KEY>/knowledge/analyses/*.md`
  - `data/wiki/spaces/<SPACE_KEY>/knowledge/lint/report.md`
- space 인덱스: `data/wiki/spaces/<SPACE_KEY>/index.md`
- space 누적 요약: `data/wiki/spaces/<SPACE_KEY>/synthesis.md`
- space 운영 로그: `data/wiki/spaces/<SPACE_KEY>/log.md`
- 이미지: `data/wiki/spaces/<SPACE_KEY>/assets/*`
- 그래프: `data/wiki/global/graph.json`
- 글로벌 인덱스: `data/wiki/global/index.md`
- DB: `data/db/app.db`

## 화면

- `문서 홈`: Space별 최근 문서와 synthesis 링크
- `문서 홈`: Space별 knowledge 문서와 synthesis 링크
- `문서 상세`: knowledge 문서 중심, 필요 시 원문 링크와 raw 근거 링크 사용
- `문서 이력`: 버전 목록과 과거 snapshot 조회
- `Synthesis`: Space별 누적 요약 페이지
- `Knowledge`: entity / concept / analysis / lint 문서 렌더링
- `Graph View`: 계층 링크 + 위키 링크 동시 시각화
- `Wiki Q&A`: 선택된 space 또는 전체 위키 기준 답변, 분석 문서 저장

## Assistant 저장 흐름

1. 사용자가 우측 하단 `위키에게 묻기` 버튼으로 질문합니다.
2. assistant는 먼저 `index.md` 를 읽어 후보를 좁히고, 관련 원문/지식 문서를 읽어 답합니다.
3. 특정 space 화면에서는 답변을 `knowledge/analyses/` 아래 markdown로 저장할 수 있습니다.
4. 저장 시 `index.md`, `global/index.md`, `log.md`, `lint/report.md` 가 함께 갱신됩니다.

## LLM Knowledge Layer

이 프로젝트는 raw Confluence snapshot만 저장하지 않습니다. gist 방향에 맞춰 `raw page layer` 위에 `knowledge layer`를 같이 유지하고, UI는 knowledge-first로 동작합니다.

- raw page layer:
  - 최신 원문 markdown
  - history snapshot
  - assets
- knowledge layer:
  - entity 문서
  - concept 문서
  - assistant 저장 analysis 문서
  - lint report

assistant가 찾는 근거는 `knowledge 우선, raw fallback` 순서를 따릅니다. 저장된 analysis 문서는 이후 질문에서도 근거로 재활용됩니다.

## Assistant Answer Save Flow

1. space 페이지 또는 문서 화면에서 우측 하단 `위키에게 묻기` 버튼을 엽니다.
2. 질문 후 답변 카드 하단의 `위키에 저장` 버튼을 누릅니다.
3. 분석 문서는 현재 선택된 space의 `knowledge/analyses/` 아래에 저장됩니다.
4. 저장 즉시 `space index`, `global index`, `log.md` 가 함께 갱신됩니다.

전체 홈처럼 `selected_space=all` 인 화면에서는 저장 대상 space가 없으므로 저장 버튼을 노출하지 않습니다.

## 운영 스키마 문서

위키 구조와 유지 규칙은 [AGENTS.md](./AGENTS.md) 에 정리되어 있습니다. 새로운 knowledge kind나 ingest 규칙을 추가할 때 이 문서를 먼저 맞추는 것을 권장합니다.

## 설계 문서

- [docs/plans/2026-04-06-confluence-wiki-design.md](./docs/plans/2026-04-06-confluence-wiki-design.md)
- [docs/plans/2026-04-06-confluence-wiki.md](./docs/plans/2026-04-06-confluence-wiki.md)
- [docs/plans/2026-04-07-persistent-llm-wiki-design.md](./docs/plans/2026-04-07-persistent-llm-wiki-design.md)
- [docs/plans/2026-04-07-persistent-llm-wiki.md](./docs/plans/2026-04-07-persistent-llm-wiki.md)
- [docs/plans/2026-04-07-llm-knowledge-layer-design.md](./docs/plans/2026-04-07-llm-knowledge-layer-design.md)
- [docs/plans/2026-04-07-llm-knowledge-layer.md](./docs/plans/2026-04-07-llm-knowledge-layer.md)
