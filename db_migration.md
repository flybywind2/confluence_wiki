# DB Migration Guide

이 문서는 현재 `markdown files + SQLite metadata` 구조를 유지하면서, 필요 시 `PostgreSQL` 로 전환하는 절차를 정리한 운영 문서입니다.

## 현재 상태

현재 기본 DB는 SQLite 입니다.

- application metadata: SQLite
- document source of truth: markdown files
- sync/job metadata: SQLite

현재 SQLite 운영 보강 사항:

- `WAL`
- `busy_timeout=30000`
- `foreign_keys=ON`
- `temp_store=MEMORY`
- `wal_autocheckpoint=1000`
- sync lease 기반 단일 writer 차단
- sync 후 `PRAGMA optimize`, `PRAGMA wal_checkpoint(PASSIVE)`

이 정도면 단일 인스턴스 운영에는 충분하지만, 아래 상황이면 PostgreSQL 전환이 맞습니다.

- 여러 프로세스에서 앱을 띄우는 경우
- admin 작업과 sync가 자주 겹치는 경우
- 동시 사용자가 늘어 SQLite write contention이 체감되는 경우
- 향후 vector search, 더 복잡한 queue state, 운영 리포트가 필요해지는 경우

## 권장 전환 방향

권장 방향은 `PostgreSQL` 단일 전환입니다.

- metadata 원본을 PostgreSQL로 이동
- markdown 파일 저장은 유지
- 필요 시 이후 `pgvector` 를 추가

지금 단계에서는 `vector DB`까지 한 번에 넣기보다:

1. SQLite -> PostgreSQL
2. 안정화
3. 필요 시 `pgvector`

순서가 더 안전합니다.

## 사전 준비

### 1. PostgreSQL 준비

예시:

```text
host: db.example.internal
port: 5432
database: confluence_wiki
user: wiki_app
password: ********
```

### 2. 애플리케이션 의존성

PostgreSQL 드라이버를 설치합니다.

권장 예시:

```bash
python -m pip install psycopg[binary]
```

현재 프로젝트가 `psycopg` 를 기본 의존성으로 갖고 있지 않다면, 전환 시 `pyproject.toml` 에 추가해야 합니다.

### 3. 환경 변수 변경

`.env` 의 `DATABASE_URL` 을 PostgreSQL URL로 바꿉니다.

예시:

```env
DATABASE_URL=postgresql+psycopg://wiki_app:password@db.example.internal:5432/confluence_wiki
```

## 전환 절차

### 1. 서비스 중지

웹 서버와 admin sync 작업을 멈춥니다.

- web app stop
- internal scheduler stop
- external scheduler stop

### 2. 현재 markdown / SQLite 백업

최소 백업 대상:

- `WIKI_ROOT`
- `CACHE_ROOT`
- 기존 SQLite 파일

예시:

```powershell
Copy-Item -Recurse D:\data\wiki D:\backup\wiki-20260411
Copy-Item -Recurse D:\data\cache D:\backup\cache-20260411
Copy-Item D:\data\db\app.db D:\backup\app-20260411.db
```

### 3. PostgreSQL schema 생성

Alembic으로 현재 스키마를 생성합니다.

```bash
alembic upgrade head
```

### 4. 데이터 이전

현재 구조는 markdown 파일이 문서 원본이고, DB는 메타데이터 저장소입니다. 따라서 이전은 두 층으로 나뉩니다.

#### A. 파일 계층

그대로 유지합니다.

- `spaces/.../pages/*.md`
- `spaces/.../history/...`
- `global/...`

#### B. DB 메타데이터 계층

권장 방식은 **재적재**입니다.

1. PostgreSQL schema만 준비
2. 앱을 PostgreSQL에 연결
3. 필요한 경우 bootstrap / incremental / rebuild를 다시 수행

이 방식이 안전한 이유:

- markdown 파일은 그대로 유지됨
- DB는 파생 metadata 성격이 강함
- SQLite -> PostgreSQL row dump 마이그레이션보다 재구성이 단순함

### 5. 앱 재시작

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 6. 검증

최소 검증 항목:

- 로그인 가능
- 홈/검색/그래프 로딩 가능
- knowledge 조회 가능
- admin operations 접근 가능
- bootstrap / incremental 실행 가능
- query wiki 생성 가능

## 권장 운영 검증 명령

```bash
python -m pytest tests/db/test_migrations.py tests/api -q
python -m pytest tests/services/test_query_jobs.py tests/services/test_sync_service.py -q
```

## 롤백 전략

문제가 생기면 다음 순서로 롤백합니다.

1. 앱 중지
2. `.env` 의 `DATABASE_URL` 을 기존 SQLite로 복원
3. 기존 SQLite 파일과 markdown 백업 확인
4. 앱 재시작

즉 현재 구조는 markdown 파일이 유지되므로, DB 전환 실패 시 복구가 비교적 단순합니다.

## Postgres 전환 후 권장 추가 작업

PostgreSQL 전환 후에는 아래를 순차적으로 검토하면 됩니다.

### 1. index / uniqueness 강화

- `pages(space_id, confluence_page_id)` unique
- `page_versions(page_id, version_number)` unique
- `knowledge_documents(space_id, kind, slug)` unique

### 2. queue/job persistence

현재 query/admin job 상태는 메모리 큐 기반입니다. PostgreSQL 전환 후에는 DB persisted queue로 확장할 여지가 있습니다.

### 3. pgvector

질의 응답 품질을 더 끌어올릴 때 추가합니다.

추천 순서:

1. PostgreSQL 안정화
2. chunk table 설계
3. embedding 저장
4. hybrid retrieval

## 한 줄 권장안

- 지금 당장 운영 안정성이 필요하면 `SQLite + 현재 최적화`로 유지
- 다중 프로세스 / 다중 사용자 / 고급 검색까지 갈 계획이면 `PostgreSQL` 로 먼저 옮기고, `pgvector` 는 그 다음 단계로 진행
