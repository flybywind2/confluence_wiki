# SQLite Scale Guide

이 문서는 `confluence_wiki`를 SQLite로 운영할 때 문서 수를 최대화하기 위한 기준을 정리합니다.

## 결론

SQLite로도 수천 개의 raw 문서는 충분히 감당할 수 있습니다. 하지만 안정성은 `문서 수`보다 아래 조건에 더 크게 좌우됩니다.

- 동시 사용자 수
- bootstrap / incremental 빈도
- knowledge 재작성 빈도
- graph / lint를 얼마나 자주 전역 재구성하는지

권장 기준:

- `1천 ~ 3천 raw 문서`: 현재 구조 보강으로 운영 가능
- `3천 ~ 8천 raw 문서`: FTS5, 부분 재구성, 강한 write queue 필요
- `8천 ~ 1만+ raw 문서`: SQLite로 버틸 수는 있어도 운영 여유가 작아지고 PostgreSQL 전환 준비가 필요

## 반드시 지켜야 할 운영 원칙

### 1. SQLite는 SSD에 둔다

- `DATABASE_URL`의 sqlite 파일은 로컬 SSD에 둡니다.
- 네트워크 드라이브, 동기화 폴더, 느린 외장 스토리지는 피합니다.

### 2. writer는 하나만 유지한다

SQLite는 single writer 전제가 중요합니다.

- bootstrap
- incremental
- 지식 재작성
- admin write

이 경로는 가능한 한 하나의 queue로 직렬화합니다.

### 3. 전역 재구성을 online 경로에서 줄인다

가장 비싼 작업은 아래입니다.

- global knowledge rebuild
- global lint rebuild
- global graph rebuild
- raw 전체 파일 스캔 검색

이 작업이 sync 직후 경로에 남아 있으면 문서 수가 늘수록 급격히 느려집니다.

## 추천 DB 설정

현재 코드의 SQLite 기본 설정은 다음과 같습니다.

- `journal_mode=WAL`
- `synchronous=NORMAL`
- `busy_timeout=30000`
- `foreign_keys=ON`
- `temp_store=MEMORY`
- `wal_autocheckpoint=1000`

이 조합은 대부분의 읽기/쓰기 혼합 workload에서 적절합니다.

## 권장 스키마 보강

다음 unique 제약과 인덱스를 추천합니다.

### Unique 제약

- `pages(space_id, confluence_page_id)`
- `pages(space_id, slug)`
- `page_versions(page_id, version_number)`
- `wiki_documents(page_id)`
- `knowledge_documents(space_id, kind, slug)`

### 인덱스

- `page_links(source_page_id, target_page_id, link_type)`
- `sync_runs(space_id, status, started_at)`
- `sync_schedules(space_id, enabled, run_time)`

## 검색 최대화 방안

문서 수가 커질수록 raw 파일을 직접 열어 검색하는 방식은 버리게 됩니다.

권장:

- SQLite `FTS5` 사용
- raw markdown에서 plain text chunk 생성
- query wiki, assistant, 검색은 먼저 FTS5에서 후보를 찾고 나서 상세 처리

이렇게 하면:

- 파일 I/O가 줄고
- query/wiki 생성 속도가 빨라지고
- raw 1만 건 근처까지도 lexical 검색 기반은 유지하기 쉬워집니다

## 동기화 경로 권장안

### 좋은 구조

- raw page 하나 처리 -> 즉시 commit
- changed page ids 추적
- affected knowledge topics만 재작성
- lint/index/graph는 부분 갱신 또는 별도 배치

### 피해야 할 구조

- sync 1건마다 global knowledge 전체 rebuild
- raw 전체 파일 스캔 후 query 생성
- admin read 시 lease cleanup write 수행

## maintenance 권장안

### online

- `PRAGMA optimize`
- 가벼운 checkpoint

### nightly / offline

- `wal_checkpoint(TRUNCATE)`
- `VACUUM`
- orphan markdown/asset cleanup
- global lint/full graph rebuild

## graph 운영 기준

1만 문서급에서 전체 graph를 브라우저에 주는 건 실용적이지 않습니다.

권장:

- `space`, `topic`, `query 결과` 기준 subgraph
- 전역 graph는 요약만 제공
- 브라우저 렌더링은 node cap 적용

## PostgreSQL 전환 시점

아래가 반복되면 전환을 시작하는 게 맞습니다.

- `database is locked` 회피 코드가 계속 늘어난다
- heavy sync가 운영 시간에 자주 겹친다
- raw 문서 수가 1만 개에 근접한다
- multi-user write가 많다
- FTS5와 부분 갱신을 넣어도 sync tail latency가 길다

그 시점부터는 SQLite 튜닝보다 PostgreSQL 전환이 더 저렴합니다.
