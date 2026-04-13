# SQLite Scale Design

**Goal:** SQLite를 유지한 상태에서 이 프로젝트가 감당할 수 있는 raw/knowledge 문서 수를 최대화한다.

**Current Constraint:** 병목은 저장 용량이 아니라 `single writer`, `전역 재구성`, `파일 스캔`, `동기 sync 경로의 heavy work`에 있다.

**Recommendation:** SQLite는 유지하되, `조합 인덱스/unique 제약`, `FTS5 검색`, `부분 재구성`, `단일 write queue`, `maintenance 분리`를 우선 적용한다. PostgreSQL 전환은 1만 문서급 운영 여유가 필요해지는 시점의 2단계 과제로 둔다.

---

## Problem Statement

현재 코드베이스는 이미 아래 최적화를 일부 적용한 상태다.

- WAL, `busy_timeout`, `synchronous=NORMAL`
- sync lease 기반 single writer 보호
- raw page 단위 commit
- sync 후 knowledge 부분 재구성

하지만 SQLite 기준 규모 확장의 실제 병목은 여전히 남아 있다.

- raw/knowledge 검색이 파일과 markdown 본문에 많이 의존한다.
- lint/index/graph 일부는 여전히 전체 상태를 기준으로 다시 계산한다.
- knowledge/query 생성 경로가 LLM과 파일 I/O를 많이 사용한다.
- admin write, bootstrap, incremental, regenerate가 같은 SQLite writer를 경쟁한다.

즉, SQLite에서 감당 가능한 최대 문서 수를 올리려면 `DB 설정`보다 `연산 구조`를 바꾸는 쪽이 더 중요하다.

## Scaling Targets

- `1천 ~ 3천 raw 문서`: 현재 구조 보강으로 충분히 가능
- `3천 ~ 8천 raw 문서`: FTS5, 부분 갱신, 강한 단일 writer 규율 필요
- `8천 ~ 1만+ raw 문서`: SQLite로 버티는 건 가능할 수 있으나 운영 여유가 작고 PostgreSQL 전환 준비가 필요

핵심 기준은 raw 문서 수보다 `동시 사용자 수`, `sync 빈도`, `knowledge 재생성 빈도`, `graph 범위`다.

## Approaches

### Approach A: SQLite 유지 + 구조 최적화

권장안이다.

- SQLite를 메타/문서 저장소로 유지
- raw 검색은 FTS5로 전환
- sync 이후 파생물은 모두 부분 갱신
- heavy maintenance는 online 경로에서 분리

장점:

- 현재 구조를 유지하면서도 체감 성능을 크게 올릴 수 있다.
- 가장 적은 운영 복잡도로 효과를 낸다.

단점:

- 1만+ 문서와 다중 writer 운영에는 여전히 한계가 있다.

### Approach B: SQLite 유지 + 파일 기반 검색 유지

비추천이다.

- 파일 스캔과 markdown 파싱을 계속 유지한 채 세부 튜닝만 수행

장점:

- 구현량이 적다.

단점:

- 문서 수가 늘어날수록 한계가 매우 빨리 드러난다.

### Approach C: PostgreSQL로 즉시 전환

장기적으로는 맞을 수 있으나, SQLite 최대화 자체의 답은 아니다.

장점:

- 동시성과 운영 여유가 크다.

단점:

- 지금 당장 필요한 병목 제거보다 migration 비용이 먼저 든다.

## Priority Changes

### 1. 조합 인덱스와 unique 제약 추가

추천 제약:

- `pages(space_id, confluence_page_id)` unique
- `pages(space_id, slug)` unique
- `page_versions(page_id, version_number)` unique
- `wiki_documents(page_id)` unique
- `knowledge_documents(space_id, kind, slug)` unique

추천 인덱스:

- `page_links(source_page_id, target_page_id, link_type)`
- `sync_runs(space_id, status, started_at)`
- `sync_schedules(space_id, enabled, run_time)`

### 2. raw 검색을 FTS5로 전환

권장 테이블:

- `raw_page_chunks`
  - `id`
  - `page_id`
  - `chunk_no`
  - `space_id`
  - `title`
  - `body_text`
  - `updated_at`
- `raw_page_chunks_fts`
  - FTS5 virtual table
  - `title`, `body_text`

전략:

- sync 시 page markdown에서 plain text chunk 생성
- chunk insert/update 후 FTS5 index refresh
- query wiki, assistant, 검색은 먼저 FTS5로 후보를 고른 뒤 상세 처리

### 3. knowledge/lint/index/graph를 부분 갱신으로 통일

원칙:

- raw page 변경 -> affected topics만 재작성
- lint는 touched topic + touched space만 재평가
- index는 changed page/knowledge 문서만 반영
- graph는 전체 rebuild 대신 changed subgraph만 cache patch

### 4. 단일 writer queue 강제

원칙:

- bootstrap
- incremental
- knowledge regenerate
- admin write
- schedule-triggered sync

이 모든 write 작업은 하나의 write queue를 통해 직렬화한다.

### 5. heavy maintenance 분리

online:

- `PRAGMA optimize`
- 가벼운 checkpoint

offline/nightly:

- `wal_checkpoint(TRUNCATE)`
- `VACUUM`
- orphan file cleanup
- global lint/full graph rebuild

## Graph Strategy

1만 건에서 전체 graph를 브라우저에 주는 건 실용적이지 않다.

권장:

- 기본은 `space`, `query`, `topic` 단위 subgraph
- 전역 graph는 summary/aggregate만 제공
- 브라우저 렌더링은 node cap을 둔다

## Operational Guidelines

- DB와 wiki root는 SSD에 둔다.
- 네트워크 드라이브에 SQLite를 두지 않는다.
- bootstrap과 대량 incremental은 업무 시간대와 분리한다.
- sync와 heavy regenerate를 동시에 허용하지 않는다.
- stale lease와 failed job cleanup을 주기적으로 점검한다.

## Success Criteria

- `1 page bootstrap`이 전체 raw/knowledge 수와 무관하게 빠르게 완료된다.
- query/wiki 생성이 raw 전체 파일 스캔 없이 동작한다.
- `database is locked`가 운영상 드물어진다.
- 전역 graph/lint rebuild가 사용자 요청 경로에 남아 있지 않다.

## Recommendation Summary

실행 순서는 아래가 맞다.

1. 조합 인덱스/unique 제약
2. FTS5 기반 raw 검색
3. partial rebuild 확대
4. single writer queue 강제
5. heavy maintenance offline 분리
6. 이후에도 1만 문서 운영이 필요하면 PostgreSQL 전환
