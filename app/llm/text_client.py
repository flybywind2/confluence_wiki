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
