# Obsidian Compatibility Design

## 목표

생성되는 markdown 파일을 Obsidian vault에서 바로 열어도 구조가 유지되게 만든다. FastAPI UI도 같은 파일을 그대로 렌더링할 수 있어야 한다.

## 저장 형식

- YAML frontmatter
  - `title`
  - `aliases`
  - `tags`
  - source metadata
- Obsidian wikilink
  - `[[spaces/DEMO/pages/root-page-100|Root Page]]`
  - `[[spaces/DEMO/knowledge/concepts/core-topics|DEMO 핵심 개념]]`
- Obsidian image embed
  - `![[spaces/DEMO/assets/diagram.png]]`
- Obsidian callout
  - `> [!info] 이미지 설명`

## 앱 적응

- 렌더러는 Obsidian wikilink/embed를 FastAPI route와 static route로 변환한다.
- assistant excerpt/hint parser도 같은 형식을 이해한다.

## 프롬프트 강화

- 인덱스용 one-line summary
- fact card
- concept synthesis
- Q&A

모든 프롬프트에 `추정 금지`, `근거 우선`, `출력 섹션 고정`을 명시한다.
