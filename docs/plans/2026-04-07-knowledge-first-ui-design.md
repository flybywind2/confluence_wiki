# Knowledge-First UI Design

## 목표

사용자가 보는 위키를 `raw Confluence page 목록`이 아니라 `주제형 knowledge wiki`로 바꾼다. raw page는 내부 근거 계층으로 남기되, 기본 홈/검색/최근 문서/UI graph에서는 숨긴다.

## 사용자 노출 규칙

- 기본 노출:
  - `synthesis`
  - `concept`
  - `analysis`
  - `lint`
- 기본 비노출:
  - raw page
  - entity 문서
- raw page 접근:
  - direct URL
  - knowledge 문서의 근거 링크
  - assistant source link fallback

## 문서 생성 규칙

- raw page마다 사람용 메인 페이지를 만들지 않는다.
- raw page는 먼저 `fact card` 로 압축한다.
- 여러 fact card를 묶어 `concept` 문서를 3~8개 정도 생성한다.
- `synthesis` 는 space 전체 knowledge hub 역할을 한다.

## LLM 프롬프트 방향

- 사실 기반 정리만 허용
- 입력 문서에 없는 내용 추정 금지
- 표는 핵심 수치/항목/결론만 반영
- 이미지 설명은 문맥상 의미가 있을 때만 포함
- 고정 섹션:
  - 개요
  - 핵심 사실
  - 운영 포인트
  - 관련 문서
  - 원문 근거

## UI 변경

- 홈/space 홈/검색: knowledge 문서만 노출
- page 상세: knowledge 문서를 기본 대상으로 사용
- graph: knowledge graph를 기본값으로 사용
- assistant: knowledge 우선, raw fallback
