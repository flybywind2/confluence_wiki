## 동기화 체크리스트

1. mirror URL과 prod URL이 환경 변수에서 분리되어 있는지 확인합니다.
2. `CONF_VERIFY_SSL=false` 설정이 의도대로 적용되었는지 점검합니다.
3. 외부 스케줄러가 `bootstrap` 또는 `sync`를 호출할 수 있는지 확인합니다.
4. 증분 동기화 후 graph cache가 갱신되었는지 확인합니다.

> 데모용 문서이므로 실제 운영 절차 대신 화면 검증 포인트를 중심으로 적었습니다.

## 관련 문서

- [운영 대시보드](/spaces/DEMO/pages/ops-dashboard-9002)
- [데모 홈](/spaces/DEMO/pages/demo-home-9001)
