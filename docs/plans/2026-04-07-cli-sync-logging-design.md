# CLI Sync Logging Design

## 목표

`python -m app.cli bootstrap ...` 와 `python -m app.cli sync ...` 실행 시 터미널에서 진행 상황을 바로 확인할 수 있게 한다. 기본 실행에서는 요약 진행 로그를 출력하고, `--verbose` 옵션이 있을 때만 attachment/이미지 처리 같은 상세 로그를 추가한다.

## 접근

- `app.cli` 에 `--verbose` 옵션을 추가한다.
- CLI 시작 시 Python `logging` 을 설정한다.
- `SyncService` 는 `print` 대신 `logging` 을 사용해 진행 로그를 남긴다.
- 기본 `INFO` 로그:
  - 시작: mode, space, root page id 또는 증분 대상 수
  - 진행: 현재 페이지 `n/N`, page id, title
  - 완료: 처리 페이지 수, asset 수
- `DEBUG` 로그:
  - attachment 다운로드 시작/완료
  - 본문 이미지 치환
  - materialized view 재빌드 시작/완료

## 범위

- 포함:
  - CLI 옵션 추가
  - sync/bootstrap 진행 로그
  - README 실행 로그 설명 갱신
- 제외:
  - 웹 UI 실시간 진행률
  - DB 기반 job progress API
  - 로그 파일 로테이션

## 테스트

- CLI parser 가 `--verbose` 를 받는지 확인
- `SyncService.run_incremental()` 실행 시 기본 로그가 stdout/stderr 로 출력되는지 확인
- `--verbose` 레벨에서 `DEBUG` 로그가 노출되는지 확인
