from __future__ import annotations

import logging
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

try:
    import google.generativeai as genai  # type: ignore
    from google.api_core import exceptions as google_exceptions  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    genai = None
    google_exceptions = None


LOGGER = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    model: str


class TutorLLMClient:
    """Wrapper around Google Gemini API with graceful fallbacks."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.api_key = os.getenv("GEMINI_API")
        if self.is_configured():
            genai.configure(api_key=self.api_key)

    def is_configured(self) -> bool:
        return bool(self.api_key) and genai is not None

    def generate_reply(self, prompt: str, images: Optional[Iterable[Path]] = None) -> str:
        if not self.is_configured():
            LOGGER.warning("LLM not configured properly; returning placeholder response")
            return (
                "[LLM is not configured. Set the GEMINI_API environment variable with a valid API key.\n"
                "Prompt received was processed locally for testing purposes.]"
            )

        model = genai.GenerativeModel(self.config.model)

        parts = [prompt]
        for image_path in images or []:
            if not image_path:
                continue
            try:
                parts.append(self._load_image_part(image_path))
            except FileNotFoundError:
                LOGGER.warning("Image not found for prompt: %s", image_path)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.exception("Failed to attach image %s: %s", image_path, exc)

        try:
            response = model.generate_content(parts)
        except Exception as exc:  # pragma: no cover - network/API failure
            LOGGER.exception("LLM call failed: %s", exc)
            if google_exceptions and isinstance(exc, google_exceptions.NotFound):
                return (
                    "[Автоматический ответ недоступен: указанная модель недоступна. "
                    "Проверьте имя модели в настройках и выберите поддерживаемую модель Gemini.]"
                )
            return "[Автоматический ответ недоступен: ошибка при обращении к LLM.]"

        text = getattr(response, "text", None)
        if not text:
            LOGGER.warning("LLM returned empty response")
            return "[LLM не вернул ответ.]"

        return text.strip()

    @staticmethod
    def _load_image_part(image_path: Path):
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type:
            mime_type = "image/png"
        data = image_path.read_bytes()
        return {"mime_type": mime_type, "data": data}
