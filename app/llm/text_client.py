from __future__ import annotations

import os
import uuid

from openai import OpenAI

from app.core.config import Settings, get_settings


class TextLLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if self.settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = self.settings.openai_api_key

    def _client(self) -> OpenAI:
        headers = {
            "x-dep-ticket": self.settings.llm_dep_ticket or "",
            "Send-System-Name": self.settings.llm_send_system_name or "",
            "User-Id": self.settings.llm_user_id or "",
            "User-Type": self.settings.llm_user_type or "",
            "Prompt-Msg-Id": str(uuid.uuid4()),
            "Completion-Msg-Id": str(uuid.uuid4()),
        }
        return OpenAI(base_url=self.settings.llm_base_url, default_headers=headers)

    def summarize(self, text: str) -> str:
        if not text.strip():
            return ""
        system_prompt = (
            "당신은 Confluence 원문을 위키 인덱스용 한 줄 요약으로 압축하는 시스템입니다. "
            "추정하지 말고 문서에 명시된 사실만 사용하세요. "
            "한국어 한 문장으로, 120자 이내로, 핵심 대상과 목적이 드러나게 작성하세요."
        )
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text[:4000]},
                ],
            )
            return completion.choices[0].message.content or ""
        except Exception:
            return text.splitlines()[0][:180]

    def summarize_fact_card(self, title: str, text: str) -> str:
        if not text.strip():
            return ""
        if not self.settings.openai_api_key:
            return self._fallback_fact_card(title, text)
        system_prompt = (
            "당신은 Confluence 원문을 주제형 wiki용 fact card로 정리하는 시스템입니다.\n"
            "규칙:\n"
            "- 제공된 문서에 없는 내용 추정 금지\n"
            "- 표는 핵심 항목, 수치, 결론만 남기기\n"
            "- 이미지 설명은 문맥상 중요한 내용만 반영\n"
            "- 중복 설명 제거\n"
            "- 한국어로 작성\n"
            "출력 섹션은 정확히 다음 다섯 개만 사용하세요: 개요, 핵심 사실, 운영 포인트, 관련 문서, 원문 근거"
        )
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"제목: {title}\n\n본문:\n{text[:5000]}"},
                ],
            )
            return completion.choices[0].message.content or self._fallback_fact_card(title, text)
        except Exception:
            return self._fallback_fact_card(title, text)

    def synthesize_keyword_page(
        self,
        space_key: str,
        keyword: str,
        fact_cards: list[dict[str, str]],
        related_keywords: list[str],
    ) -> str:
        if not fact_cards:
            return ""
        if not self.settings.openai_api_key:
            return self._fallback_keyword_page(space_key, keyword, fact_cards, related_keywords)
        payload = "\n\n".join(
            [
                "\n".join(
                    [
                        f"문서 제목: {item['title']}",
                        f"문서 요약: {item['summary']}",
                        f"fact card:\n{item['fact_card']}",
                    ]
                )
                for item in fact_cards
            ]
        )
        system_prompt = (
            "당신은 여러 fact card를 키워드 중심 wiki 문서로 통합하는 시스템입니다.\n"
            "규칙:\n"
            "- fact card에 없는 내용 추정 금지\n"
            "- 같은 사실은 한 번만 정리\n"
            "- 키워드와 직접 관련 있는 사실만 남기기\n"
            "- 관련 키워드는 입력 fact card에서 자연스럽게 이어지는 단어만 사용하기\n"
            "- 원문 문서 링크를 관련 문서와 원문 근거 섹션에 포함하기\n"
            "- 한국어로 작성\n"
            "출력 섹션은 정확히 다음 다섯 개만 사용하세요: 개요, 핵심 사실, 관련 문서, 관련 키워드, 원문 근거"
        )
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Space: {space_key}\n키워드: {keyword}\n관련 키워드: {', '.join(related_keywords)}\n\n입력:\n{payload[:9000]}",
                    },
                ],
            )
            return completion.choices[0].message.content or self._fallback_keyword_page(space_key, keyword, fact_cards, related_keywords)
        except Exception:
            return self._fallback_keyword_page(space_key, keyword, fact_cards, related_keywords)

    def answer_question(self, question: str, contexts: list[dict[str, str]]) -> str:
        if not contexts:
            return "현재 범위에서 답변 근거가 될 문서를 찾지 못했습니다."

        context_text = "\n\n".join(
            [
                "\n".join(
                    [
                        f"문서 제목: {item['title']}",
                        f"Space: {item['space_key']}",
                        f"문서 종류: {item.get('kind', 'page')}",
                        "문서 경로: "
                        + (item.get("href") or f"/spaces/{item['space_key']}/pages/{item['slug']}"),
                        f"발췌: {item['excerpt']}",
                    ]
                )
                for item in contexts
            ]
        )

        if not self.settings.openai_api_key:
            return self._fallback_answer(question, contexts)

        system_prompt = (
            "당신은 Confluence Wiki assistant입니다.\n"
            "규칙:\n"
            "- 제공된 참고 문서에 있는 사실만 사용\n"
            "- 확실하지 않으면 모른다고 명시\n"
            "- 문서 간 공통점과 차이점은 분리해서 설명\n"
            "- 답변은 한국어로 간결하게 작성\n"
            "- 필요하면 마지막에 '근거 문서:' 한 줄로 핵심 근거 제목만 정리"
        )
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"질문:\n{question}\n\n참고 문서:\n{context_text}",
                    },
                ],
            )
            return completion.choices[0].message.content or self._fallback_answer(question, contexts)
        except Exception:
            return self._fallback_answer(question, contexts)

    @staticmethod
    def _fallback_answer(question: str, contexts: list[dict[str, str]]) -> str:
        lead = contexts[0]
        lines = [f"질문: {question}", "", f"가장 관련성이 높은 문서는 '{lead['title']}' 입니다.", lead["excerpt"][:280]]
        if len(contexts) > 1:
            lines.append("")
            lines.append("함께 참고한 문서:")
            lines.extend(f"- {item['space_key']}: {item['title']}" for item in contexts[1:])
        return "\n".join(lines).strip()

    @staticmethod
    def _fallback_fact_card(title: str, text: str) -> str:
        compact = " ".join(text.split())
        excerpt = compact[:240]
        return "\n".join(
            [
                f"# {title}",
                "",
                "## 개요",
                "",
                excerpt or "정보 없음",
                "",
                "## 핵심 사실",
                "",
                f"- {excerpt[:120]}" if excerpt else "- 정보 없음",
                "",
                "## 운영 포인트",
                "",
                "- 운영 시 원문 확인 필요",
                "",
                "## 원문 근거",
                "",
                f"- {title}",
            ]
        ).strip()

    @staticmethod
    def _fallback_keyword_page(
        space_key: str,
        keyword: str,
        fact_cards: list[dict[str, str]],
        related_keywords: list[str],
    ) -> str:
        lines = [
            f"# {keyword}",
            "",
            "## 개요",
            "",
            f"{space_key} space에서 '{keyword}' 키워드와 직접 연결되는 원문을 묶어 정리한 문서입니다.",
            "",
            "## 핵심 사실",
            "",
        ]
        lines.extend(f"- {item['title']}: {item['summary']}" for item in fact_cards)
        lines.extend(["", "## 관련 문서", ""])
        lines.extend(f"- [[spaces/{space_key}/pages/{item['slug']}|{item['title']}]]" for item in fact_cards)
        lines.extend(["", "## 관련 키워드", ""])
        if related_keywords:
            lines.extend(f"- [[spaces/{space_key}/knowledge/keywords/{item}|{item}]]" for item in related_keywords)
        else:
            lines.append("- 관련 키워드가 아직 충분히 추출되지 않았습니다.")
        lines.extend(["", "## 원문 근거", ""])
        lines.extend(f"- [[spaces/{space_key}/pages/{item['slug']}|{item['title']}]]" for item in fact_cards)
        return "\n".join(lines).strip()
