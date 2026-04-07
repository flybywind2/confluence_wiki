# Keyword Pages Design

**Date:** 2026-04-07

## Goal

Confluence raw page를 그대로 전면 노출하지 않고, 본문에서 기계적으로 추출한 주요 키워드별 wiki 페이지를 생성해 사용자가 흩어진 문서를 주제 단위로 빠르게 파악할 수 있게 한다.

## Requirements

- raw Confluence page는 계속 수집/보존하지만 기본 UI에서는 숨긴다.
- `concept` 중심 구조 대신 `keyword` 문서를 기본 지식 레이어로 사용한다.
- 키워드는 페이지 제목이 아니라 본문/요약에서 빈도 기반으로 추출한다.
- 많이 나온 단어는 새로운 keyword page를 만든다.
- 빈도가 낮더라도 이미 관련 keyword page가 있으면 그 페이지에 내용을 추가한다.
- 관련 page가 없으면 새 keyword page를 만든다.
- `analysis`, `lint`, `synthesis`는 유지한다.
- assistant, 검색, graph view는 keyword page를 우선 사용한다.

## Approach

### 1. Knowledge model

- `KnowledgeDocument.kind`에 `keyword`를 추가한다.
- `entity`는 내부 근거용으로만 유지한다.
- `keyword`는 UI 기본 문서 유형으로 노출한다.
- 기존 `concept`은 더 이상 새로 만들지 않고, rebuild 시 제거 대상에 포함한다.

### 2. Keyword extraction

- 입력은 raw page 제목, summary, markdown body다.
- 토큰은 한글/영문/숫자 2자 이상 정규식으로 추출한다.
- stopword와 space key, 위키 공통어는 제거한다.
- 빈도 카운트는 summary보다 body를 우선한다.
- 문서 단위 출현 수와 전체 출현 수를 함께 사용해 상위 키워드를 선택한다.
- 기본 threshold는 `2개 이상 문서에 등장` 또는 `전체 출현 3회 이상`으로 둔다.

### 3. Keyword page generation

- 각 raw page는 하나 이상의 keyword에 연결된다.
- 우선 해당 페이지의 상위 빈도 키워드에 fact card를 추가한다.
- keyword page가 이미 있으면 source 목록과 요약을 누적 갱신한다.
- 적합한 키워드가 하나도 없으면 대표 토큰 1개를 fallback으로 사용한다.
- keyword page 본문 구성:
  - 개요
  - 핵심 사실
  - 관련 문서
  - 관련 키워드
  - 원문 근거

### 4. UI and graph

- 홈/space 홈/검색 기본 결과는 `keyword`, `analysis`, `lint`, `synthesis`만 보여준다.
- `concept` 필터는 `keyword`로 교체한다.
- graph view의 knowledge 모드는 keyword node 중심으로 그린다.
- edge 유형:
  - `keyword-source`
  - `keyword-related`
  - `analysis-keyword`
  - `synthesis-keyword`

### 5. Error handling

- keyword 추출 결과가 빈약해도 rebuild는 실패시키지 않는다.
- LLM은 keyword page 합성의 보조 역할만 하고, 추출 기준은 항상 deterministic token frequency가 우선이다.
- raw 문서가 적거나 짧을 때는 소수 keyword page만 생성한다.

### 6. Testing

- demo seed 결과에서 `concepts` 대신 `keywords` 문서가 생성되는지 검증한다.
- 홈/검색이 raw page 대신 keyword page를 기본 노출하는지 검증한다.
- graph knowledge view가 keyword node를 반환하는지 검증한다.
- rebuild 시 기존 `concept` 문서가 제거되고 `keyword` 문서가 갱신되는지 검증한다.
