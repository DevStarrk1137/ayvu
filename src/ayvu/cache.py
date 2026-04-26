from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


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


class TranslationCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(SCHEMA)
        self.connection.commit()

    def get(self, text: str, source: str, target: str) -> str | None:
        row = self.connection.execute(
            """
            SELECT translated_text
            FROM translations
            WHERE source_lang = ?
              AND target_lang = ?
              AND original_text_hash = ?
            """,
            (source, target, text_hash(text)),
        ).fetchone()
        return row[0] if row else None

    def set(self, text: str, translated_text: str, source: str, target: str) -> None:
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
            (source, target, text_hash(text), text, translated_text),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "TranslationCache":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

