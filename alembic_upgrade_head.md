# Alembic Upgrade Head Guide

이 문서는 `alembic upgrade head` 를 실제 운영 환경에서 어떻게 실행하는지 정리한 실행 가이드입니다.

## 이 명령이 하는 일

`alembic upgrade head` 는 현재 코드 기준 최신 migration revision까지 DB schema를 올립니다.

이 프로젝트에서는 다음 상황에서 실행합니다.

- 새 테이블이 추가됐을 때
- 컬럼이 추가되거나 바뀌었을 때
- auth / sync / knowledge / scheduler 관련 schema가 바뀌었을 때

예를 들어 최근에는 `sync_leases` 테이블 추가 후 이 명령이 필요합니다.

## 실행 위치

항상 저장소 루트에서 실행합니다.

- 저장소 루트: [D:\Python\confluence_wiki\repo_clone](D:\Python\confluence_wiki\repo_clone)

이 위치에 아래 파일이 있어야 합니다.

- [D:\Python\confluence_wiki\repo_clone\alembic.ini](D:\Python\confluence_wiki\repo_clone\alembic.ini)
- [D:\Python\confluence_wiki\repo_clone\alembic\env.py](D:\Python\confluence_wiki\repo_clone\alembic\env.py)

## 공통 전제 조건

### 1. 의존성 설치

```powershell
cd D:\Python\confluence_wiki\repo_clone
python -m pip install -e ".[dev]"
```

또는 Python 3.10 명시:

```powershell
cd D:\Python\confluence_wiki\repo_clone
py -3.10 -m pip install -e ".[dev]"
```

### 2. `.env` 확인

Alembic은 결국 애플리케이션의 `DATABASE_URL` 을 기준으로 대상 DB를 잡습니다. 실행 전에 `.env` 의 `DATABASE_URL` 을 먼저 확인해야 합니다.

확인 예시:

```powershell
cd D:\Python\confluence_wiki\repo_clone
Get-Content .env
```

### 3. 서버/배치 정지 권장

SQLite에서는 특히 중요합니다.

- web app stop
- bootstrap / incremental stop
- internal scheduler stop
- external scheduler stop

PostgreSQL도 migration 중에는 동시 schema 변경을 피하는 편이 안전합니다.

## SQLite 실행 예시

### 예시 환경

`.env` 예:

```env
DATABASE_URL=sqlite:///./data/db/app.db
WIKI_ROOT=./data/wiki
CACHE_ROOT=./data/cache
```

### 권장 실행 순서

1. 서버 중지
2. SQLite 파일 백업
3. migration 실행
4. 현재 revision 확인
5. 서버 재시작

### PowerShell 예시

```powershell
cd D:\Python\confluence_wiki\repo_clone
Copy-Item .\data\db\app.db .\data\db\app-before-upgrade.db
python -m alembic upgrade head
python -m alembic current
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Python 3.10 명시 예시

```powershell
cd D:\Python\confluence_wiki\repo_clone
Copy-Item .\data\db\app.db .\data\db\app-before-upgrade.db
py -3.10 -m alembic upgrade head
py -3.10 -m alembic current
py -3.10 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Linux/macOS 예시

```bash
cd /opt/confluence_wiki
cp ./data/db/app.db ./data/db/app-before-upgrade.db
python -m alembic upgrade head
python -m alembic current
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## PostgreSQL 실행 예시

### 예시 환경

`.env` 예:

```env
DATABASE_URL=postgresql+psycopg://wiki_app:password@db.example.internal:5432/confluence_wiki
WIKI_ROOT=./data/wiki
CACHE_ROOT=./data/cache
```

추가로 PostgreSQL 드라이버가 필요합니다.

```powershell
cd D:\Python\confluence_wiki\repo_clone
python -m pip install psycopg[binary]
```

### 권장 실행 순서

1. PostgreSQL 연결 정보 확인
2. migration 실행
3. current / heads 확인
4. 서버 재시작

### PowerShell 예시

```powershell
cd D:\Python\confluence_wiki\repo_clone
python -m pip install psycopg[binary]
python -m alembic upgrade head
python -m alembic current
python -m alembic heads
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Python 3.10 명시 예시

```powershell
cd D:\Python\confluence_wiki\repo_clone
py -3.10 -m pip install psycopg[binary]
py -3.10 -m alembic upgrade head
py -3.10 -m alembic current
py -3.10 -m alembic heads
py -3.10 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Linux/macOS 예시

```bash
cd /opt/confluence_wiki
python -m pip install psycopg[binary]
python -m alembic upgrade head
python -m alembic current
python -m alembic heads
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 실행 결과 확인 명령

현재 DB가 어느 revision에 있는지:

```bash
python -m alembic current
```

코드 기준 최신 revision이 무엇인지:

```bash
python -m alembic heads
```

전체 migration 이력 보기:

```bash
python -m alembic history
```

## 자주 쓰는 점검 시나리오

### 1. migration 전 현재 상태 확인

```powershell
cd D:\Python\confluence_wiki\repo_clone
python -m alembic current
python -m alembic heads
```

`current` 와 `heads` 가 다르면 아직 적용되지 않은 migration이 있다는 뜻입니다.

### 2. migration 후 앱 검증

```powershell
cd D:\Python\confluence_wiki\repo_clone
python -m pytest tests\db\test_migrations.py tests\api -q
```

### 3. 특정 DB URL로 임시 실행

`.env` 를 안 바꾸고 임시로 대상 DB를 바꾸고 싶으면, PowerShell에서 환경변수를 먼저 덮어쓴 뒤 실행합니다.

SQLite 예시:

```powershell
cd D:\Python\confluence_wiki\repo_clone
$env:DATABASE_URL = "sqlite:///./data/db/tmp.db"
python -m alembic upgrade head
```

PostgreSQL 예시:

```powershell
cd D:\Python\confluence_wiki\repo_clone
$env:DATABASE_URL = "postgresql+psycopg://wiki_app:password@db.example.internal:5432/confluence_wiki"
python -m alembic upgrade head
```

## 실패할 때 확인할 것

### `alembic.ini` 또는 `env.py` 를 못 찾는 경우

원인:

- 저장소 루트가 아닌 곳에서 실행

해결:

```powershell
cd D:\Python\confluence_wiki\repo_clone
python -m alembic upgrade head
```

### `sqlalchemy.exc.OperationalError` 가 나는 경우

SQLite라면 보통:

- 서버가 DB를 점유 중
- 다른 sync job이 돌고 있음
- 파일 권한 문제

해결:

1. 서버 중지
2. scheduler 중지
3. 다시 실행

### PostgreSQL 연결 실패

원인:

- `DATABASE_URL` 오타
- `psycopg` 미설치
- 방화벽/계정/비밀번호 문제

확인:

```powershell
python -m pip show psycopg
```

## rollback 예시

### SQLite

```powershell
cd D:\Python\confluence_wiki\repo_clone
Remove-Item .\data\db\app.db
Copy-Item .\data\db\app-before-upgrade.db .\data\db\app.db
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### PostgreSQL

PostgreSQL rollback은 보통 backup/restore 또는 별도 downgrade 전략이 필요합니다. 운영에서는 `upgrade` 전에 snapshot 또는 DB backup을 떠두는 쪽이 맞습니다.

## 한 줄 권장안

- SQLite: 서버와 sync를 멈추고 백업 후 `python -m alembic upgrade head`
- PostgreSQL: 드라이버 설치와 `DATABASE_URL` 확인 후 `python -m alembic upgrade head`
