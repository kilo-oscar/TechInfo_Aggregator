from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests


GOOGLE_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
JAPANESE_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
BASE_DIR = Path(__file__).resolve().parent
TRANSLATION_USAGE_PATH = BASE_DIR / "instance" / "translation_usage.json"
DEFAULT_MONTHLY_CHARACTER_LIMIT = 450_000


def contains_japanese(text: str | None) -> bool:
    return bool(text and JAPANESE_PATTERN.search(text))


def needs_japanese_translation(source_type: str | None, title: str | None, summary: str | None) -> bool:
    if source_type not in {"news", "paper"}:
        return False
    title = (title or "").strip()
    summary = (summary or "").strip()
    return bool(title or summary) and (
        (bool(title) and not contains_japanese(title))
        or (bool(summary) and not contains_japanese(summary))
    )


class TranslationUnavailable(RuntimeError):
    pass


class TranslationQuotaExceeded(RuntimeError):
    pass


def get_monthly_character_limit() -> int:
    raw = os.getenv("GOOGLE_TRANSLATE_MONTHLY_CHARACTER_LIMIT", str(DEFAULT_MONTHLY_CHARACTER_LIMIT)).strip()
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise ValueError("GOOGLE_TRANSLATE_MONTHLY_CHARACTER_LIMIT must be an integer") from exc


class TranslationUsageTracker:
    def __init__(self, path: Path = TRANSLATION_USAGE_PATH) -> None:
        self.path = path

    def current_month(self) -> str:
        return datetime.now().strftime("%Y-%m")

    def load(self) -> dict:
        if not self.path.exists():
            return {"months": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"months": {}}
        return payload if isinstance(payload, dict) and isinstance(payload.get("months"), dict) else {"months": {}}

    def used_characters(self, month: str | None = None) -> int:
        month = month or self.current_month()
        entry = self.load()["months"].get(month, {})
        try:
            return max(0, int(entry.get("characters", 0)))
        except (AttributeError, TypeError, ValueError):
            return 0

    def ensure_available(self, requested_characters: int, limit: int) -> None:
        used = self.used_characters()
        if limit <= 0 or used + requested_characters > limit:
            raise TranslationQuotaExceeded(
                f"monthly translation character limit reached: used={used}, "
                f"requested={requested_characters}, limit={limit}"
            )

    def record(self, characters: int) -> None:
        payload = self.load()
        month = self.current_month()
        used = self.used_characters(month)
        payload["months"][month] = {
            "characters": used + max(0, characters),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class GoogleCloudTranslator:
    provider_name = "google-cloud-translation-v2"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 30,
        usage_tracker: TranslationUsageTracker | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("GOOGLE_TRANSLATE_API_KEY", "")).strip()
        self.timeout = timeout
        self.session = requests.Session()
        self.usage_tracker = usage_tracker or TranslationUsageTracker()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def translate(self, texts: list[str], target: str = "ja") -> tuple[list[str], str]:
        normalized = [str(text or "").strip() for text in texts]
        nonempty_indexes = [index for index, text in enumerate(normalized) if text]
        if not nonempty_indexes:
            return normalized, ""
        if not self.available:
            raise TranslationUnavailable("GOOGLE_TRANSLATE_API_KEY is not configured")
        requested_characters = sum(len(normalized[index]) for index in nonempty_indexes)
        monthly_limit = get_monthly_character_limit()
        self.usage_tracker.ensure_available(requested_characters, monthly_limit)

        response = self.session.post(
            GOOGLE_TRANSLATE_URL,
            params={"key": self.api_key},
            json={
                "q": [normalized[index] for index in nonempty_indexes],
                "target": target,
                "format": "text",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        translations = response.json().get("data", {}).get("translations", [])
        if len(translations) != len(nonempty_indexes):
            raise RuntimeError("translation response count did not match request")

        output = list(normalized)
        detected_languages = []
        for index, translated in zip(nonempty_indexes, translations):
            output[index] = html.unescape(str(translated.get("translatedText", "")).strip())
            detected = str(translated.get("detectedSourceLanguage", "")).strip()
            if detected:
                detected_languages.append(detected)
        detected_language = detected_languages[0] if detected_languages else ""
        self.usage_tracker.record(requested_characters)
        return output, detected_language


def build_translation_fields(data: dict, translator: GoogleCloudTranslator | None = None) -> dict:
    title = data.get("title") or ""
    summary = data.get("raw_summary") or ""
    if not needs_japanese_translation(data.get("source_type"), title, summary):
        return {}
    translator = translator or GoogleCloudTranslator()
    if not translator.available:
        return {}
    translated, detected_language = translator.translate([title, summary])
    return {
        "translated_title": translated[0] or None,
        "translated_summary": translated[1] or None,
        "source_language": detected_language or None,
        "translation_provider": translator.provider_name,
        "translated_at": datetime.utcnow(),
    }
