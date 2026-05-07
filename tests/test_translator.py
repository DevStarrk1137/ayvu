from __future__ import annotations

import requests
import pytest

from ayvu.translator import LibreTranslateTranslator, TranslatorError


class FakeSession:
    def __init__(self, responses: list[requests.Response | requests.exceptions.RequestException]) -> None:
        self.responses = responses
        self.posts: list[tuple[str, dict[str, str], float]] = []

    def post(self, url: str, *, json: dict[str, str], timeout: float) -> requests.Response:
        self.posts.append((url, json, timeout))
        response = self.responses.pop(0)
        if isinstance(response, requests.exceptions.RequestException):
            raise response
        return response


def make_response(status_code: int, body: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode("utf-8")
    response.url = "http://localhost:5000/translate"
    return response


def test_libretranslate_posts_payload_and_parses_response() -> None:
    session = FakeSession([make_response(200, '{"translatedText": "Ola"}')])
    translator = LibreTranslateTranslator(url="http://localhost:5000/", timeout=3.0, retries=0)
    translator.session = session

    result = translator.translate("Hello", "en", "pt")

    assert result == "Ola"
    assert session.posts == [
        (
            "http://localhost:5000/translate",
            {"q": "Hello", "source": "en", "target": "pt", "format": "text"},
            3.0,
        )
    ]


def test_libretranslate_returns_empty_text_without_http_call() -> None:
    session = FakeSession([])
    translator = LibreTranslateTranslator(retries=0)
    translator.session = session

    assert translator.translate("", "en", "pt") == ""
    assert session.posts == []


def test_libretranslate_retries_5xx_before_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    session = FakeSession(
        [
            make_response(503, "temporarily unavailable"),
            make_response(200, '{"translatedText": "Tudo certo"}'),
        ]
    )
    translator = LibreTranslateTranslator(retries=1)
    translator.session = session
    monkeypatch.setattr("ayvu.translator.time.sleep", lambda delay: sleeps.append(delay))

    result = translator.translate("All right", "en", "pt")

    assert result == "Tudo certo"
    assert len(session.posts) == 2
    assert sleeps == [0.5]


def test_libretranslate_reports_http_error() -> None:
    session = FakeSession([make_response(400, "bad language pair")])
    translator = LibreTranslateTranslator(retries=0)
    translator.session = session

    with pytest.raises(TranslatorError) as error:
        translator.translate("Hello", "en", "xx")

    assert "LibreTranslate HTTP error 400: bad language pair" in str(error.value)


def test_libretranslate_reports_invalid_json_response() -> None:
    session = FakeSession([make_response(200, "not-json")])
    translator = LibreTranslateTranslator(retries=0)
    translator.session = session

    with pytest.raises(TranslatorError) as error:
        translator.translate("Hello", "en", "pt")

    assert "LibreTranslate response was not valid JSON" in str(error.value)


def test_libretranslate_reports_missing_translated_text() -> None:
    session = FakeSession([make_response(200, '{"translatedText": 42}')])
    translator = LibreTranslateTranslator(retries=0)
    translator.session = session

    with pytest.raises(TranslatorError) as error:
        translator.translate("Hello", "en", "pt")

    assert "LibreTranslate response did not include translatedText" in str(error.value)


def test_libretranslate_reports_connection_error_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    session = FakeSession(
        [
            requests.exceptions.ConnectionError("refused"),
            requests.exceptions.ConnectionError("refused"),
        ]
    )
    translator = LibreTranslateTranslator(url="http://localhost:5000", retries=1)
    translator.session = session
    monkeypatch.setattr("ayvu.translator.time.sleep", lambda delay: sleeps.append(delay))

    with pytest.raises(TranslatorError) as error:
        translator.translate("Hello", "en", "pt")

    assert "Could not connect to LibreTranslate at http://localhost:5000/translate" in str(error.value)
    assert len(session.posts) == 2
    assert sleeps == [0.5]


def test_libretranslate_reports_timeout() -> None:
    session = FakeSession([requests.exceptions.Timeout("slow")])
    translator = LibreTranslateTranslator(timeout=1.5, retries=0)
    translator.session = session

    with pytest.raises(TranslatorError) as error:
        translator.translate("Hello", "en", "pt")

    assert "LibreTranslate request timed out after 1.5 seconds" in str(error.value)
