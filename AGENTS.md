# Wiki Schema

이 저장소의 위키는 `raw source -> persistent wiki -> schema` 3계층을 기준으로 운영한다.

## Goals

- Confluence mirror 원문은 읽기 전용 source of truth로 취급한다.
- `wiki/` 아래 markdown는 LLM이 유지하는 영속적 지식 계층이다.
- 새 source를 읽거나 질문에 답한 결과는 기존 wiki를 갱신하는 방식으로 반영한다.
- `index.md` 와 `log.md` 는 항상 최신으로 유지한다.

## Directory Conventions

- `spaces/<SPACE>/pages/`
  Confluence 원문 페이지를 동기화한 최신 markdown.
- `spaces/<SPACE>/history/<slug>/v0001.md`
  페이지 버전별 snapshot.
- `global/knowledge/keywords/`
  여러 space의 raw page를 통합해 만든 대표 주제 문서.
- `global/knowledge/queries/`
  사용자가 입력한 검색 키워드로 raw page 전체를 탐색해 만든 query 문서.
- `global/knowledge/analyses/`
  질문 결과, 비교표, 해석, 후속 탐구 결과를 저장한 분석 문서.
- `global/knowledge/lint/report.md`
  전체 위키 health-check 결과.
- `spaces/<SPACE>/index.md`
  해당 space의 raw page와 global knowledge 문서를 source 기준으로 필터링한 카탈로그.
- `spaces/<SPACE>/log.md`
  append-only 작업 로그.
- `spaces/<SPACE>/synthesis.md`
  현재 space의 누적 synthesis.

## Page Rules

- 모든 문서는 YAML frontmatter 를 가진 markdown 파일로 저장한다.
- 내부 지식 문서는 가능한 한 기존 페이지를 덮어쓰지 말고 관련 entity/keyword/analysis 문서를 갱신한다.
- 링크는 가능한 한 `/spaces/...` 경로 또는 `[[SPACE/slug]]` 형태를 사용한다.
- 표는 markdown으로 안전하게 표현 가능할 때만 변환하고, 병합 셀이 있으면 HTML table fallback을 유지한다.
- 이미지는 로컬 asset으로 저장하고, 중요한 이미지는 설명 텍스트를 본문에 남긴다.

## Ingest Workflow

1. mirror에서 source를 읽는다.
2. 최신 page markdown과 version snapshot을 쓴다.
3. global keyword/query/analysis/lint 문서를 갱신한다.
4. `index.md`, `synthesis.md`, `log.md`, `graph.json` 을 갱신한다.
5. 필요 시 `lint/report.md` 를 다시 생성한다.

## Query Workflow

1. raw page 전체와 global knowledge 문서를 함께 후보로 본다.
2. 관련 page/knowledge 문서를 읽고 답을 합성한다.
3. 답변이 재사용 가치가 있으면 `global/knowledge/analyses/` 아래 분석 문서로 저장한다.
4. 저장 시 `index.md`, `log.md`, `lint/report.md` 를 함께 갱신한다.

## Lint Workflow

- 최소한 아래 항목을 점검한다.
- Missing summaries
- Orphan pages
- History coverage gaps
- Missing cross references or stale synthesis candidates

## Editing Discipline

- Confluence raw source 자체는 수정하지 않는다.
- wiki는 markdown 파일 기반 artifact 이므로 DB보다 파일을 우선 진실원으로 본다.
- knowledge 문서는 사용자 질문과 새 source를 통해 계속 갱신되는 누적 자산으로 다룬다.
