from __future__ import annotations

import json
import os
import uuid

from openai import OpenAI

from app.core.config import Settings, get_settings

WEAK_TOPIC_COMPONENTS = {
    "analysis",
    "check",
    "guide",
    "policy",
    "개요",
    "공유",
    "대응",
    "대상",
    "배포",
    "범위",
    "요약",
    "운영",
    "이슈",
    "일정",
    "정책",
    "절차",
    "점검",
    "진행",
    "주간",
    "지표",
    "지원",
    "현황",
    "흐름",
    "회의",
    "회의록",
    "검토",
    "결과",
    "공통",
    "과정",
    "변경",
    "보고",
    "상태",
    "설명",
    "유형",
    "항목",
}


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

    # 한국어 번역:
    # - 문서를 인덱스용 한 줄 요약으로 압축한다.
    # - 문서에 명시된 사실만 사용하고 추정하지 않는다.
    # - '삼성 DS', 'DS부문', 'Device Solutions'는 모두 DS부문으로 본다.
    # - 원문에 '디스플레이'가 없으면 디스플레이나 삼성디스플레이로 해석하지 않는다.
    # - 결과는 반드시 한국어 한 문장으로 작성한다.
    def _summary_system_prompt(self) -> str:
        return (
            "You compress Confluence source documents into a single-line wiki index summary. "
            "Use only facts that are explicitly stated in the document and do not infer missing details. "
            "Treat 'Samsung DS', 'DS Division', and 'Device Solutions' as the DS division. "
            "If the source does not explicitly mention 'display', do not reinterpret the content as display or Samsung Display. "
            "Respond in Korean with exactly one concise sentence, within 120 characters, and make the main subject and purpose obvious."
        )

    # 한국어 번역:
    # - 원문을 fact card 형식으로 정리한다.
    # - 제공된 문서에 없는 내용은 추정하지 않는다.
    # - 표는 핵심 항목과 수치만 남기고, 이미지 설명은 중요할 때만 반영한다.
    # - 중복 설명을 제거한다.
    # - 결과는 반드시 한국어로, 지정된 섹션만 사용한다.
    def _fact_card_system_prompt(self) -> str:
        return (
            "You turn a Confluence source page into a topic-oriented wiki fact card.\n"
            "Rules:\n"
            "- Use only facts present in the provided document.\n"
            "- Treat 'Samsung DS', 'DS Division', and 'Device Solutions' as the DS division.\n"
            "- If the source does not explicitly mention 'display', do not rewrite it as display or Samsung Display.\n"
            "- Keep only the important items, numbers, and conclusions from tables.\n"
            "- Include image descriptions only when they matter to the document meaning.\n"
            "- Remove duplicated explanations.\n"
            "- Respond in Korean.\n"
            "Use exactly five sections and no others: overview, key facts, operational points, related documents, and source evidence. "
            "Write the section content in Korean."
        )

    # 한국어 번역:
    # - 여러 fact card를 하나의 주제 페이지로 합친다.
    # - 주제와 직접 관련된 사실만 남기고 중복은 제거한다.
    # - 관련 문서와 원문 근거에는 문서 링크를 포함한다.
    # - 결과는 반드시 한국어로, 지정된 섹션만 사용한다.
    def _topic_page_system_prompt(self) -> str:
        return (
            "You merge multiple fact cards into one topic-focused wiki page.\n"
            "Rules:\n"
            "- Use only facts that appear in the fact cards.\n"
            "- Treat 'Samsung DS', 'DS Division', and 'Device Solutions' as the DS division.\n"
            "- If the source does not explicitly mention 'display', do not rewrite it as display or Samsung Display.\n"
            "- Keep each fact only once.\n"
            "- Keep only facts that are directly relevant to the topic title.\n"
            "- Use only naturally connected related topics derived from the provided fact cards.\n"
            "- Include source document links in the related documents and source evidence sections.\n"
            "- Respond in Korean.\n"
            "Use exactly five sections and no others: overview, key facts, related documents, related topics, and source evidence. "
            "Write the section content in Korean."
        )

    # 한국어 번역:
    # - 규칙으로 뽑은 후보 주제 중에서 대표 표현을 고른다.
    # - 후보로 주어진 표현만 그대로 선택한다.
    # - 단일 토큰보다 의미 묶음 표현을 우선한다.
    # - 결과는 JSON만 반환한다.
    def _topic_selection_system_prompt(self) -> str:
        return (
            "You select representative topic phrases for a wiki page from rule-extracted candidates.\n"
            "Rules:\n"
            "- Select only phrases that already exist in the candidate list.\n"
            "- Prefer meaningful phrase bundles such as 'AI Portal', 'AI Agent', and 'DS Assistant' over split single tokens.\n"
            "- Reject weak standalone operational nouns such as 'operations', 'status', 'check', 'state', 'flow', 'plan', 'response', 'policy', and 'procedure' unless they are part of a stronger multi-token phrase already present in the candidate list.\n"
            "- Use the page title first. If the title is weak, rely on headings, table headers, and link text before plain body frequency.\n"
            "- Reuse an existing topic when the document clearly belongs to it, even if the exact phrase is not frequent.\n"
            "- Treat 'Samsung DS', 'DS Division', and 'Device Solutions' as the DS division.\n"
            "- If the source does not explicitly mention 'display', do not reinterpret it as display or Samsung Display.\n"
            "- Keep the output stable and conservative. Do not invent new phrases.\n"
            "- Return JSON only in the form {\"topics\": [\"topic one\", \"topic two\"]}.\n"
            "- Any free-text field, if absolutely necessary, must be in Korean."
        )

    # 한국어 번역:
    # - 참고 문서에 있는 사실만으로 질문에 답한다.
    # - 확실하지 않으면 모른다고 말한다.
    # - 문서 간 공통점과 차이점을 분리해 설명할 수 있다.
    # - 답변은 반드시 한국어로 작성한다.
    def _qa_system_prompt(self) -> str:
        return (
            "You are the Confluence Wiki assistant.\n"
            "Rules:\n"
            "- Use only facts that appear in the provided source documents.\n"
            "- Treat 'Samsung DS', 'DS Division', and 'Device Solutions' as the DS division.\n"
            "- If the source does not explicitly mention 'display', do not reinterpret it as display or Samsung Display.\n"
            "- If the answer is uncertain, say that you do not know.\n"
            "- When helpful, separate common points from differences across documents.\n"
            "- Respond in Korean.\n"
            "- If useful, end with one short evidence line using a Korean label for source documents."
        )

    # 한국어 번역:
    # - 기존 wiki 상태와 현재 문서를 함께 보고, 이 문서가 기여해야 할 주제를 고른다.
    # - 기존 topic이 맞으면 반드시 기존 이름을 재사용한다.
    # - 후보는 규칙 기반 후보를 참고하되, 의미적으로 더 적절한 기존 topic이 있으면 그쪽을 택한다.
    # - 결과는 JSON만 반환한다.
    def _topic_proposal_system_prompt(self) -> str:
        return (
            "You are the wiki topic editor for an evolving knowledge base.\n"
            "Rules:\n"
            "- Look at the current wiki state, the existing topic inventory, and the source document together.\n"
            "- Reuse an existing topic title whenever the document clearly contributes to that topic.\n"
            "- Use candidate topics only as hints, not as mandatory choices.\n"
            "- Prefer stable, meaningful topic names over temporary phrases.\n"
            "- Treat 'Samsung DS', 'DS Division', and 'Device Solutions' as the DS division.\n"
            "- If the source does not explicitly mention 'display', do not reinterpret it as display or Samsung Display.\n"
            "- Respond in Korean only when returning any natural-language field.\n"
            "- Return JSON only in the form {\"topics\": [\"topic one\", \"topic two\"]}.\n"
            "- Return between minimum_count and 8 topics when enough strong candidates exist."
        )

    # 한국어 번역:
    # - 주제 페이지의 성격을 분류해서 적절한 집필 틀을 고른다.
    # - 결과는 JSON만 반환한다.
    def _topic_type_system_prompt(self) -> str:
        return (
            "You classify the editorial type of a wiki topic page.\n"
            "Choose exactly one topic type from: concept, entity, process, decision_log, comparison.\n"
            "Treat 'Samsung DS', 'DS Division', and 'Device Solutions' as the DS division.\n"
            "If the source does not explicitly mention 'display', do not reinterpret it as display or Samsung Display.\n"
            "Return JSON only in the form {\"topic_type\": \"concept\"}."
        )

    # 한국어 번역:
    # - 기존 topic page를 새 근거로 갱신한다.
    # - 기존 내용은 가능한 유지하되, 중복은 제거하고 새 근거를 통합한다.
    # - 모순이나 빈 곳이 있으면 명시한다.
    # - 결과는 한국어 markdown이다.
    def _topic_update_system_prompt(self) -> str:
        return (
            "You are maintaining a long-lived wiki page.\n"
            "Your job is to update the existing topic page with new evidence instead of rewriting it from scratch.\n"
            "Rules:\n"
            "- Preserve useful existing structure and facts when they are still supported.\n"
            "- Integrate new evidence without repeating the same point.\n"
            "- If documents disagree, mention the disagreement explicitly.\n"
            "- If the evidence is still incomplete, say what remains unclear.\n"
            "- Treat 'Samsung DS', 'DS Division', and 'Device Solutions' as the DS division.\n"
            "- If the source does not explicitly mention 'display', do not reinterpret it as display or Samsung Display.\n"
            "- Respond in Korean markdown.\n"
            "- Use a structure appropriate to the topic type instead of forcing one fixed template."
        )

    def summarize(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": self._summary_system_prompt()},
                    {"role": "user", "content": text[:4000]},
                ],
            )
            return completion.choices[0].message.content or ""
        except Exception:
            return text.splitlines()[0][:180]

    def summarize_fact_card(self, title: str, text: str, prefer_llm: bool = True) -> str:
        if not text.strip():
            return ""
        if not prefer_llm or not self.settings.openai_api_key:
            return self._fallback_fact_card(title, text)
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": self._fact_card_system_prompt()},
                    {"role": "user", "content": f"Title: {title}\n\nSource:\n{text[:5000]}"},
                ],
            )
            return completion.choices[0].message.content or self._fallback_fact_card(title, text)
        except Exception:
            return self._fallback_fact_card(title, text)

    def synthesize_topic_page(
        self,
        space_key: str,
        topic: str,
        fact_cards: list[dict[str, str]],
        related_topics: list[str],
        prefer_llm: bool = True,
    ) -> str:
        if not fact_cards:
            return ""
        if not prefer_llm or not self.settings.openai_api_key:
            return self._fallback_topic_page(space_key, topic, fact_cards, related_topics)
        payload = "\n\n".join(
            [
                "\n".join(
                    [
                        f"Document title: {item['title']}",
                        f"Document summary: {item['summary']}",
                        f"Fact card:\n{item['fact_card']}",
                    ]
                )
                for item in fact_cards
            ]
        )
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": self._topic_page_system_prompt()},
                    {
                        "role": "user",
                        "content": (
                            f"Space: {space_key}\n"
                            f"Topic: {topic}\n"
                            f"Related topics: {', '.join(related_topics)}\n\n"
                            f"Input fact cards:\n{payload[:9000]}"
                        ),
                    },
                ],
            )
            return completion.choices[0].message.content or self._fallback_topic_page(space_key, topic, fact_cards, related_topics)
        except Exception:
            return self._fallback_topic_page(space_key, topic, fact_cards, related_topics)

    def select_topic_phrases(
        self,
        page_title: str,
        page_summary: str,
        candidates: list[dict[str, object]],
        existing_topics: list[str],
        minimum_count: int,
    ) -> list[str]:
        if not candidates:
            return []
        if not self.settings.openai_api_key:
            return self._fallback_select_topic_phrases(candidates, minimum_count)

        payload = {
            "page_title": page_title,
            "page_summary": page_summary,
            "minimum_count": minimum_count,
            "existing_topics": existing_topics,
            "candidates": candidates,
        }
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": self._topic_selection_system_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
            )
            content = completion.choices[0].message.content or ""
            selected = self._parse_topic_selection(content, candidates)
            if selected:
                return selected
        except Exception:
            pass
        return self._fallback_select_topic_phrases(candidates, minimum_count)

    def answer_question(self, question: str, contexts: list[dict[str, str]]) -> str:
        if not contexts:
            return "현재 범위에서 답변 근거가 될 문서를 찾지 못했습니다."

        context_text = "\n\n".join(
            [
                "\n".join(
                    [
                        f"Document title: {item['title']}",
                        f"Space: {item['space_key']}",
                        f"Document kind: {item.get('kind', 'page')}",
                        "Document path: "
                        + (item.get("href") or f"/spaces/{item['space_key']}/pages/{item['slug']}"),
                        f"Excerpt: {item['excerpt']}",
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
                    {"role": "system", "content": self._qa_system_prompt()},
                    {
                        "role": "user",
                        "content": f"Question:\n{question}\n\nSource documents:\n{context_text}",
                    },
                ],
            )
            return completion.choices[0].message.content or self._fallback_answer(question, contexts)
        except Exception:
            return self._fallback_answer(question, contexts)

    def propose_topics_for_document(
        self,
        *,
        page_title: str,
        page_summary: str,
        body_excerpt: str,
        existing_topics: list[str],
        wiki_state: str,
        candidate_topics: list[str],
        minimum_count: int = 1,
    ) -> list[str]:
        if not self.settings.openai_api_key:
            return self._fallback_propose_topics_for_document(
                page_title=page_title,
                page_summary=page_summary,
                body_excerpt=body_excerpt,
                existing_topics=existing_topics,
                candidate_topics=candidate_topics,
                minimum_count=minimum_count,
            )
        payload = {
            "page_title": page_title,
            "page_summary": page_summary,
            "body_excerpt": body_excerpt[:5000],
            "existing_topics": existing_topics[:120],
            "candidate_topics": candidate_topics[:24],
            "minimum_count": minimum_count,
            "wiki_state": wiki_state[:4000],
        }
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": self._topic_proposal_system_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
            )
            content = completion.choices[0].message.content or ""
            selected = self._parse_topic_selection(content, [{"topic": item} for item in [*candidate_topics, *existing_topics]])
            if selected:
                return selected[:5]
        except Exception:
            pass
        return self._fallback_propose_topics_for_document(
            page_title=page_title,
            page_summary=page_summary,
            body_excerpt=body_excerpt,
            existing_topics=existing_topics,
            candidate_topics=candidate_topics,
            minimum_count=minimum_count,
        )

    def classify_topic_type(
        self,
        *,
        topic: str,
        supporting_documents: list[dict[str, str]],
        existing_content: str = "",
        wiki_state: str = "",
    ) -> str:
        if not self.settings.openai_api_key:
            return self._fallback_classify_topic_type(topic=topic, existing_content=existing_content)
        payload = {
            "topic": topic,
            "supporting_documents": [
                {
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                }
                for item in supporting_documents[:8]
            ],
            "existing_content": existing_content[:3000],
            "wiki_state": wiki_state[:3000],
        }
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": self._topic_type_system_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
            )
            content = completion.choices[0].message.content or ""
            parsed = json.loads(content)
            topic_type = str(parsed.get("topic_type") or "").strip()
            if topic_type in {"concept", "entity", "process", "decision_log", "comparison"}:
                return topic_type
        except Exception:
            pass
        return self._fallback_classify_topic_type(topic=topic, existing_content=existing_content)

    def update_topic_page(
        self,
        *,
        space_key: str,
        topic: str,
        topic_type: str,
        existing_content: str,
        new_evidence: list[dict[str, str]],
        related_topics: list[str],
        wiki_state: str,
        prefer_llm: bool = True,
    ) -> str:
        if not new_evidence:
            return existing_content.strip()
        if not prefer_llm or not self.settings.openai_api_key:
            return self._fallback_update_topic_page(
                space_key=space_key,
                topic=topic,
                topic_type=topic_type,
                existing_content=existing_content,
                new_evidence=new_evidence,
                related_topics=related_topics,
            )
        payload = {
            "space_key": space_key,
            "topic": topic,
            "topic_type": topic_type,
            "existing_content": existing_content[:7000],
            "related_topics": related_topics[:8],
            "wiki_state": wiki_state[:4000],
            "new_evidence": [
                {
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "fact_card": item.get("fact_card", ""),
                    "body_excerpt": item.get("body_excerpt", "")[:2000],
                }
                for item in new_evidence[:10]
            ],
        }
        try:
            completion = self._client().chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": self._topic_update_system_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
            )
            content = (completion.choices[0].message.content or "").strip()
            if content:
                return content
        except Exception:
            pass
        return self._fallback_update_topic_page(
            space_key=space_key,
            topic=topic,
            topic_type=topic_type,
            existing_content=existing_content,
            new_evidence=new_evidence,
            related_topics=related_topics,
        )

    @classmethod
    def _parse_topic_selection(cls, content: str, candidates: list[dict[str, object]]) -> list[str]:
        candidate_titles = {str(item["topic"]): str(item["topic"]) for item in candidates}
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return []
        raw_topics = payload if isinstance(payload, list) else payload.get("topics", [])
        selected: list[str] = []
        for raw_topic in raw_topics:
            topic = str(raw_topic).strip()
            if topic in candidate_titles and topic not in selected:
                selected.append(topic)
        return selected

    @classmethod
    def _fallback_select_topic_phrases(cls, candidates: list[dict[str, object]], minimum_count: int) -> list[str]:
        ordered = sorted(candidates, key=cls._candidate_priority, reverse=True)
        selected: list[dict[str, object]] = []
        selected_topics: list[str] = []

        for candidate in ordered:
            topic = str(candidate["topic"])
            if topic in selected_topics:
                continue
            if cls._is_shadowed_candidate(candidate, selected):
                continue
            selected.append(candidate)
            selected_topics.append(topic)
            if len(selected_topics) >= minimum_count:
                break
        return selected_topics

    @classmethod
    def _candidate_priority(cls, candidate: dict[str, object]) -> tuple[int, int, int, int, str]:
        token_count = int(candidate.get("token_count") or 1)
        score = int(candidate.get("score") or 0)
        occurrences = int(candidate.get("occurrences") or 0)
        sources = {str(item) for item in candidate.get("sources") or []}
        components = [str(item) for item in candidate.get("components") or []]
        weak_component_set = {item.lower() for item in WEAK_TOPIC_COMPONENTS}
        headword = components[-1].lower() if components else ""

        structural_bonus = 0
        if "title" in sources:
            structural_bonus += 30
        if "heading" in sources:
            structural_bonus += 24
        if "table" in sources:
            structural_bonus += 14
        if "link" in sources:
            structural_bonus += 12
        if "existing" in sources:
            structural_bonus += 18

        weak_penalty = sum(1 for component in components if component.lower() in weak_component_set)
        all_ascii = all(component.isascii() for component in components if component)
        all_non_ascii = all((not component.isascii()) for component in components if component)
        mixed_penalty = 0 if all_ascii or all_non_ascii else 3
        phrase_bonus = 0
        if token_count > 1:
            if headword in {"dashboard", "portal", "runbook", "wiki", "assistant", "agent", "architecture", "flow", "policy", "guide", "이슈", "런북", "대시보드", "아키텍처", "포털", "절차", "정책", "흐름", "위키", "어시스턴트", "에이전트"}:
                phrase_bonus += 32
            elif "title" in sources or "existing" in sources:
                phrase_bonus += 34
            elif weak_penalty:
                phrase_bonus -= 10
            else:
                phrase_bonus += 20
                if all_ascii or all_non_ascii:
                    phrase_bonus += 8

        return (
            phrase_bonus + token_count,
            structural_bonus + score - (weak_penalty * 5) - mixed_penalty,
            occurrences,
            -weak_penalty,
            str(candidate.get("topic") or "").lower(),
        )

    @classmethod
    def _is_shadowed_candidate(cls, candidate: dict[str, object], selected: list[dict[str, object]]) -> bool:
        topic = str(candidate.get("topic") or "")
        token_count = int(candidate.get("token_count") or 1)
        components = {str(item).lower() for item in candidate.get("components") or []}
        weak_component_set = {value.lower() for value in WEAK_TOPIC_COMPONENTS}
        weak_components = {item for item in components if item in weak_component_set}

        if token_count == 1:
            for selected_candidate in selected:
                if int(selected_candidate.get("token_count") or 1) <= 1:
                    continue
                if topic.lower() in {str(item).lower() for item in selected_candidate.get("components") or []}:
                    return True
            return False

        if not weak_components:
            return False
        for selected_candidate in selected:
            selected_components = {str(item).lower() for item in selected_candidate.get("components") or []}
            overlap = components.intersection(selected_components)
            if overlap and selected_components != components:
                return True
        return False

    @staticmethod
    def _fallback_answer(question: str, contexts: list[dict[str, str]]) -> str:
        lead = contexts[0]
        lines = [f"질문: {question}", "", f"가장 관련성이 높은 문서는 '{lead['title']}' 입니다.", lead["excerpt"][:280]]
        if len(contexts) > 1:
            lines.append("")
            lines.append("함께 참고한 문서:")
            lines.extend(f"- {item['space_key']}: {item['title']}" for item in contexts[1:])
        return "\n".join(lines).strip()

    @classmethod
    def _fallback_propose_topics_for_document(
        cls,
        *,
        page_title: str,
        page_summary: str,
        body_excerpt: str,
        existing_topics: list[str],
        candidate_topics: list[str],
        minimum_count: int,
    ) -> list[str]:
        combined = " ".join([page_title, page_summary, body_excerpt]).lower()
        selected: list[str] = []
        for topic in sorted(existing_topics, key=lambda item: (-len(item.split()), item.lower())):
            parts = [part.lower() for part in topic.split() if part.strip()]
            if parts and all(part in combined for part in parts):
                selected.append(topic)
        for topic in candidate_topics:
            if topic not in selected:
                selected.append(topic)
        if minimum_count > 0 and len(selected) < minimum_count:
            title_tokens = [token for token in page_title.split() if token.strip()]
            fallback_topic = " ".join(title_tokens[:2]).strip()
            if fallback_topic and fallback_topic not in selected:
                selected.append(fallback_topic)
        filtered: list[str] = []
        for topic in selected:
            lower_topic = topic.lower()
            short_ascii_topic = lower_topic.isascii() and len(lower_topic) <= 2
            shadowed_by_phrase = any(
                lower_topic in {part.lower() for part in other.split()}
                for other in selected
                if other != topic and len(other.split()) > 1
            )
            if len(lower_topic.split()) == 1:
                if shadowed_by_phrase and (
                    lower_topic in {item.lower() for item in WEAK_TOPIC_COMPONENTS}
                    or short_ascii_topic
                    or (topic.isascii() and not topic.isupper())
                ):
                    continue
            filtered.append(topic)
        selected = filtered or selected
        target_count = max(minimum_count, min(len(selected), 10))
        return selected[: max(1, target_count)]

    @staticmethod
    def _fallback_classify_topic_type(*, topic: str, existing_content: str = "") -> str:
        normalized = f"{topic} {existing_content}".lower()
        if any(token in normalized for token in ["vs", "비교", "차이"]):
            return "comparison"
        if any(token in normalized for token in ["회의", "결정", "decision", "로그"]):
            return "decision_log"
        if any(token in normalized for token in ["절차", "runbook", "흐름", "process", "가이드"]):
            return "process"
        if len(topic.split()) <= 2 and topic[:1].isupper():
            return "entity"
        return "concept"

    @classmethod
    def _fallback_update_topic_page(
        cls,
        *,
        space_key: str,
        topic: str,
        topic_type: str,
        existing_content: str,
        new_evidence: list[dict[str, str]],
        related_topics: list[str],
    ) -> str:
        overview_lines = [
            f"{space_key} 범위의 raw 문서를 바탕으로 '{topic}' 주제를 누적 정리한 문서입니다."
        ]
        if existing_content.strip():
            overview_lines.append("기존 정리 내용을 유지하면서 새 근거를 통합했습니다.")

        heading_map = {
            "concept": ("## 개요", "## 핵심 사실", "## 관련 문서", "## 관련 주제", "## 원문 근거"),
            "entity": ("## 개요", "## 정체", "## 핵심 사실", "## 관련 문서", "## 원문 근거"),
            "process": ("## 개요", "## 절차 포인트", "## 운영 주의점", "## 관련 문서", "## 원문 근거"),
            "decision_log": ("## 배경", "## 결정 사항", "## 후속 조치", "## 관련 문서", "## 원문 근거"),
            "comparison": ("## 비교 개요", "## 공통점", "## 차이점", "## 관련 문서", "## 원문 근거"),
        }
        headings = heading_map.get(topic_type, heading_map["concept"])
        evidence_lines = [f"- {cls._fallback_evidence_detail(item)}" for item in new_evidence]
        related_lines = [f"- {item}" for item in related_topics] or ["- 관련 주제가 아직 충분히 정리되지 않았습니다."]
        source_lines = [
            f"- [[spaces/{item['space_key']}/pages/{item['slug']}|{item['title']}]]"
            for item in new_evidence
        ]
        section_bodies = {
            headings[0]: "\n".join(overview_lines),
            headings[1]: "\n".join(evidence_lines) or "- 정보 없음",
            headings[2]: "\n".join(
                f"- [[spaces/{item['space_key']}/pages/{item['slug']}|{item['title']}]]"
                for item in new_evidence
            )
            or "- 관련 문서 없음",
            headings[3]: "\n".join(related_lines),
            headings[4]: "\n".join(source_lines) or "- 원문 근거 없음",
        }
        lines = [f"# {topic}", ""]
        for heading in headings:
            lines.extend([heading, "", section_bodies[heading], ""])
        return "\n".join(lines).strip()

    @staticmethod
    def _fallback_fact_card(title: str, text: str) -> str:
        compact = " ".join(text.split())
        excerpt = TextLLMClient._extract_meaningful_excerpt(text) or compact[:240]
        key_fact = TextLLMClient._extract_meaningful_excerpt(text, limit=180) or excerpt[:180]
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
                f"- {key_fact}" if key_fact else "- 정보 없음",
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
    def _fallback_topic_page(
        space_key: str,
        topic: str,
        fact_cards: list[dict[str, str]],
        related_topics: list[str],
    ) -> str:
        lines = [
            f"# {topic}",
            "",
            "## 개요",
            "",
            f"{space_key} space에서 '{topic}' 주제와 직접 연결되는 원문을 묶어 정리한 문서입니다.",
            "",
            "## 핵심 사실",
            "",
        ]
        lines.extend(f"- {item['title']}: {item['summary']}" for item in fact_cards)
        lines.extend(["", "## 관련 문서", ""])
        lines.extend(f"- [[spaces/{space_key}/pages/{item['slug']}|{item['title']}]]" for item in fact_cards)
        lines.extend(["", "## 관련 주제", ""])
        if related_topics:
            lines.extend(f"- [[spaces/{space_key}/knowledge/keywords/{item}|{item}]]" for item in related_topics)
        else:
            lines.append("- 관련 주제가 아직 충분히 정리되지 않았습니다.")
        lines.extend(["", "## 원문 근거", ""])
        lines.extend(f"- [[spaces/{space_key}/pages/{item['slug']}|{item['title']}]]" for item in fact_cards)
        return "\n".join(lines).strip()

    @staticmethod
    def _extract_meaningful_excerpt(text: str, limit: int = 240) -> str:
        lines = [line.strip() for line in str(text or "").splitlines()]
        cleaned_lines: list[str] = []
        capture_key_facts = False
        for line in lines:
            if not line:
                continue
            if line.startswith("## "):
                capture_key_facts = line.lower() in {"## 핵심 사실", "## key facts", "## 절차 포인트", "## 운영 포인트"}
                continue
            normalized = line.lstrip("-* ").strip()
            if normalized.startswith("#"):
                continue
            if capture_key_facts and normalized:
                return normalized[:limit]
            if normalized:
                cleaned_lines.append(normalized)
        for line in cleaned_lines:
            if len(line) >= 12:
                return line[:limit]
        compact = " ".join(str(text or "").split())
        return compact[:limit].strip()

    @classmethod
    def _fallback_evidence_detail(cls, item: dict[str, str]) -> str:
        detail_sources = [
            item.get("fact_card", ""),
            item.get("body_excerpt", ""),
            item.get("summary", ""),
        ]
        for source in detail_sources:
            detail = cls._extract_meaningful_excerpt(source, limit=200)
            if detail:
                return detail
        return str(item.get("title") or "정보 없음")
