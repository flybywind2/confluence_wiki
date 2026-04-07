# Topic Clustering Design

## 목표

흩어진 Confluence 문서를 사용자가 주제별로 빠르게 파악할 수 있게 topic cluster, knowledge graph, facet 탐색을 추가한다.

## 접근

- 1차 clustering
  - 제목
  - one-line summary
  - fact card
  - 내부 링크
  - parent/child
- 2차 synthesis
  - LLM이 cluster 이름, 설명, 운영 포인트, 남은 질문을 정리

## cluster 문서

- 개요
- 핵심 사실
- 운영 포인트
- 대표 문서
- 관련 문서
- 남은 질문
- 원문 근거

## knowledge graph

- 노드
  - concept
  - analysis
  - synthesis
  - optional raw page
- 엣지
  - concept -> raw page
  - concept -> concept
  - analysis -> concept
  - synthesis -> concept

## facet UX

- 주제
- 문서 유형
- 최근 변경
- 분석 문서 여부
- raw 포함 여부
