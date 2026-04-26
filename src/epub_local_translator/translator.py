from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests


class TranslatorError(RuntimeError):
    pass


class Translator(ABC):
    @abstractmethod
    def translate(self, text: str, source: str, target: str) -> str:
        raise NotImplementedError


@dataclass
class LibreTranslateTranslator(Translator):
    url: str = "http://localhost:5000"
    timeout: float = 30.0
    retries: int = 2

    def __post_init__(self) -> None:
        self.endpoint = self._normalize_endpoint(self.url)
        self.session = requests.Session()

    def translate(self, text: str, source: str, target: str) -> str:
        if not text:
            return text

        payload = {
            "q": text,
            "source": source,
            "target": target,
            "format": "text",
        }
        last_error: Exception | None = None
        attempts = max(1, self.retries + 1)

        for attempt in range(1, attempts + 1):
            try:
                response = self.session.post(self.endpoint, json=payload, timeout=self.timeout)
                if response.status_code >= 500 and attempt < attempts:
                    time.sleep(0.5 * attempt)
                    continue
                response.raise_for_status()
                data = response.json()
                translated = data.get("translatedText")
                if not isinstance(translated, str):
                    raise TranslatorError("LibreTranslate response did not include translatedText")
                return translated
            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(0.5 * attempt)
                    continue
                raise TranslatorError(
                    f"Could not connect to LibreTranslate at {self.endpoint}. "
                    "Is the local translation server running?"
                ) from exc
            except requests.exceptions.Timeout as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(0.5 * attempt)
                    continue
                raise TranslatorError(f"LibreTranslate request timed out after {self.timeout} seconds") from exc
            except requests.exceptions.HTTPError as exc:
                raise TranslatorError(
                    f"LibreTranslate HTTP error {response.status_code}: {response.text[:300]}"
                ) from exc
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(0.5 * attempt)
                    continue
                raise TranslatorError(f"LibreTranslate request failed: {exc}") from exc

        raise TranslatorError(f"LibreTranslate request failed: {last_error}")

    @staticmethod
    def _normalize_endpoint(url: str) -> str:
        clean = url.rstrip("/")
        if clean.endswith("/translate"):
            return clean
        return f"{clean}/translate"


def create_translator(name: str, url: str, timeout: float = 30.0, retries: int = 2) -> Translator:
    if name != "libretranslate":
        raise ValueError(f"Unsupported translator: {name}")
    return LibreTranslateTranslator(url=url, timeout=timeout, retries=retries)

