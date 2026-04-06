from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.core.config import Settings, get_settings


class VisionClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if self.settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = self.settings.openai_api_key

    def _client(self) -> ChatOpenAI:
        headers = {
            "Content-Type": "application/json",
            "x-dep-ticket": self.settings.vlm_dep_ticket or "",
            "Send-System-Name": self.settings.vlm_send_system_name or "",
            "User-Id": self.settings.vlm_user_id or "",
            "User-Type": self.settings.vlm_user_type or "",
            "Prompt-Msg-Id": str(uuid.uuid4()),
            "Completion-Msg-Id": str(uuid.uuid4()),
        }
        return ChatOpenAI(
            base_url=self.settings.vlm_base_url,
            openai_proxy=self.settings.vlm_base_url,
            model=self.settings.vlm_model,
            default_headers=headers,
        )

    def describe_image(self, image_path: Path) -> str:
        try:
            encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
            human_message = HumanMessage(
                content=[
                    {"type": "text", "text": "이미지를 상세히 한글로 설명해주세요."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                ]
            )
            chunks = []
            for chunk in self._client().stream([human_message]):
                chunks.append(chunk.content)
            return "".join(chunks).strip()
        except Exception:
            return f"{image_path.name} 이미지"
