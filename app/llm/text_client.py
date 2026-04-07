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
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": "문서를 짧게 한국어로 요약하세요."},
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
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 Confluence 문서를 주제형 위키를 위한 fact card로 정리하는 시스템입니다. "
                            "추정하지 말고 제공된 문서만 사용하세요. 출력 섹션은 개요, 핵심 사실, 운영 포인트, 원문 근거만 사용하세요."
                        ),
                    },
                    {"role": "user", "content": f"제목: {title}\n\n본문:\n{text[:5000]}"},
                ],
            )
            return completion.choices[0].message.content or self._fallback_fact_card(title, text)
        except Exception:
            return self._fallback_fact_card(title, text)

    def synthesize_concept(self, space_key: str, topic_title: str, fact_cards: list[dict[str, str]]) -> str:
        if not fact_cards:
            return ""
        if not self.settings.openai_api_key:
            return self._fallback_concept(space_key, topic_title, fact_cards)
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
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 Confluence 원문 fact card를 주제형 wiki 문서로 통합하는 시스템입니다. "
                            "중복 제거, 추정 금지, 제공 근거만 사용. 출력 섹션은 개요, 핵심 사실, 운영 포인트, 관련 문서, 원문 근거만 사용하세요."
                        ),
                    },
                    {"role": "user", "content": f"Space: {space_key}\n주제: {topic_title}\n\n입력:\n{payload[:9000]}"},
                ],
            )
            return completion.choices[0].message.content or self._fallback_concept(space_key, topic_title, fact_cards)
        except Exception:
            return self._fallback_concept(space_key, topic_title, fact_cards)

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

        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 Confluence Wiki 도우미입니다. 반드시 제공된 문서 근거만 사용해 한국어로 간결하게 답변하고, 모르면 모른다고 답하세요.",
                    },
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
    def _fallback_concept(space_key: str, topic_title: str, fact_cards: list[dict[str, str]]) -> str:
        lines = [
            f"# {topic_title}",
            "",
            "## 개요",
            "",
            f"{space_key} space의 관련 문서를 주제별로 묶은 개념 문서입니다.",
            "",
            "## 핵심 사실",
            "",
        ]
        lines.extend(f"- {item['title']}: {item['summary']}" for item in fact_cards)
        lines.extend(["", "## 운영 포인트", ""])
        lines.extend(f"- {item['title']} 참고" for item in fact_cards[:3])
        lines.extend(["", "## 관련 문서", ""])
        lines.extend(f"- [{item['title']}]({item['href']})" for item in fact_cards)
        lines.extend(["", "## 원문 근거", ""])
        lines.extend(f"- [{item['title']}]({item['href']})" for item in fact_cards)
        return "\n".join(lines).strip()
