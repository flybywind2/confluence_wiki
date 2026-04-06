## 구조 메모

이 Space는 여러 Space가 함께 표시되는 화면을 검증하기 위한 보조 문서입니다. DEMO Space와 색상이 다르게 표시되고, graph view에서는 cross-space wiki link가 전역 화면에서만 이어집니다.

## 설계 포인트

- 파일 본문은 markdown으로 저장합니다.
- 메타데이터는 SQLite에 보관하고, 이후 MySQL/PostgreSQL로 마이그레이션할 수 있습니다.
- 이미지와 graph cache는 `WIKI_ROOT` 아래에서 정적 서빙합니다.

## 돌아가기

- [Confluence Wiki Demo 홈](/spaces/DEMO/pages/demo-home-9001)
