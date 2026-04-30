from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .domain import LanguagePair


SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    original_text_hash TEXT NOT NULL,
    original_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_lang, target_lang, original_text_hash)
);
"""


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheKey:
    text: str
    language_pair: LanguagePair

    @property
    def original_text_hash(self) -> str:
        return text_hash(self.text)


class TranslationCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(SCHEMA)
        self.connection.commit()

    def get(self, key: CacheKey) -> str | None:
        row = self.connection.execute(
            """
            SELECT translated_text
            FROM translations
            WHERE source_lang = ?
              AND target_lang = ?
              AND original_text_hash = ?
            """,
            (key.language_pair.source, key.language_pair.target, key.original_text_hash),
        ).fetchone()
        return row[0] if row else None

    def set(self, key: CacheKey, translated_text: str) -> None:
        self.connection.execute(
            """
            INSERT INTO translations (
                source_lang,
                target_lang,
                original_text_hash,
                original_text,
                translated_text
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_lang, target_lang, original_text_hash)
            DO UPDATE SET translated_text = excluded.translated_text
            """,
            (
                key.language_pair.source,
                key.language_pair.target,
                key.original_text_hash,
                key.text,
                translated_text,
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "TranslationCache":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
