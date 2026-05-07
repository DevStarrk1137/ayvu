from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

import requests


SUPPORTED_TRANSLATORS = ("libretranslate",)


class TranslatorError(RuntimeError):
    pass


class UnsupportedTranslatorError(TranslatorError):
    pass


class Translator(ABC):
    @abstractmethod
    def translate(self, text: str, source: str, target: str) -> str:
        raise NotImplementedError


class HttpSession(Protocol):
    def post(self, url: str, *, json: dict[str, str], timeout: float) -> requests.Response:
        pass


@dataclass(frozen=True)
class LibreTranslatePayload:
    text: str
    source: str
    target: str

    def as_json(self) -> dict[str, str]:
        return {
            "q": self.text,
            "source": self.source,
            "target": self.target,
            "format": "text",
        }


@dataclass(frozen=True)
class RetryPolicy:
    retries: int

    @property
    def max_attempts(self) -> int:
        return max(1, self.retries + 1)

    def attempts(self) -> range:
        return range(1, self.max_attempts + 1)

    def can_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def delay_for(self, attempt: int) -> float:
        return 0.5 * attempt


class LibreTranslateResponseParser:
    def parse(self, response: requests.Response) -> str:
        try:
            data = response.json()
        except ValueError as exc:
            raise TranslatorError("LibreTranslate response was not valid JSON") from exc

        translated = data.get("translatedText") if isinstance(data, dict) else None
        if not isinstance(translated, str):
            raise TranslatorError("LibreTranslate response did not include translatedText")
        return translated


@dataclass
class LibreTranslateTranslator(Translator):
    url: str = "http://localhost:5000"
    timeout: float = 30.0
    retries: int = 2

    def __post_init__(self) -> None:
        self.endpoint = self._normalize_endpoint(self.url)
        self.session: HttpSession = requests.Session()
        self.retry_policy = RetryPolicy(self.retries)
        self.response_parser = LibreTranslateResponseParser()

    def translate(self, text: str, source: str, target: str) -> str:
        if not text:
            return text

        payload = LibreTranslatePayload(text=text, source=source, target=target)
        last_error: Exception | None = None

        for attempt in self.retry_policy.attempts():
            try:
                response = self._post(payload)
                if self._should_retry_response(response, attempt):
                    self._wait_before_retry(attempt)
                    continue
                response.raise_for_status()
                return self.response_parser.parse(response)
            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                if self._retry_after_exception(attempt):
                    continue
                raise TranslatorError(
                    f"Could not connect to LibreTranslate at {self.endpoint}. "
                    "Is the local translation server running?"
                ) from exc
            except requests.exceptions.Timeout as exc:
                last_error = exc
                if self._retry_after_exception(attempt):
                    continue
                raise TranslatorError(f"LibreTranslate request timed out after {self.timeout} seconds") from exc
            except requests.exceptions.HTTPError as exc:
                raise self._http_error(exc) from exc
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if self._retry_after_exception(attempt):
                    continue
                raise TranslatorError(f"LibreTranslate request failed: {exc}") from exc

        raise TranslatorError(f"LibreTranslate request failed: {last_error}")

    def _post(self, payload: LibreTranslatePayload) -> requests.Response:
        return self.session.post(self.endpoint, json=payload.as_json(), timeout=self.timeout)

    def _should_retry_response(self, response: requests.Response, attempt: int) -> bool:
        return response.status_code >= 500 and self.retry_policy.can_retry(attempt)

    def _retry_after_exception(self, attempt: int) -> bool:
        if not self.retry_policy.can_retry(attempt):
            return False

        self._wait_before_retry(attempt)
        return True

    def _wait_before_retry(self, attempt: int) -> None:
        time.sleep(self.retry_policy.delay_for(attempt))

    @staticmethod
    def _http_error(exc: requests.exceptions.HTTPError) -> TranslatorError:
        response = exc.response
        if response is None:
            return TranslatorError(f"LibreTranslate HTTP error: {exc}")
        return TranslatorError(f"LibreTranslate HTTP error {response.status_code}: {response.text[:300]}")

    @staticmethod
    def _normalize_endpoint(url: str) -> str:
        clean = url.rstrip("/")
        if clean.endswith("/translate"):
            return clean
        return f"{clean}/translate"


def create_translator(name: str, url: str, timeout: float = 30.0, retries: int = 2) -> Translator:
    if name != "libretranslate":
        supported = ", ".join(SUPPORTED_TRANSLATORS)
        raise UnsupportedTranslatorError(f"Unsupported translator: {name}. Supported translators: {supported}.")
    return LibreTranslateTranslator(url=url, timeout=timeout, retries=retries)
