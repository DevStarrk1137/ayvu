from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .domain import TranslationOptions


RESUME_STATE_VERSION = 1
RUNNING_STATUS = "running"
COMPLETED_STATUS = "completed"


class ResumeStateError(ValueError):
    pass


@dataclass(frozen=True)
class TranslationResumeState:
    version: int
    status: str
    input_path: Path
    output_path: Path
    cache_path: Path
    source: str
    target: str
    translator_name: str
    url: str
    glossary_path: Path | None
    fail_fast: bool
    overwrite: bool
    timeout: float
    retries: int
    chunk_limit: int
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        input_path: Path,
        output_path: Path,
        cache_path: Path,
        translator_name: str,
        url: str,
        glossary_path: Path | None,
        options: TranslationOptions,
        overwrite: bool,
        timeout: float,
        retries: int,
    ) -> "TranslationResumeState":
        now = _utc_now()
        return cls(
            version=RESUME_STATE_VERSION,
            status=RUNNING_STATUS,
            input_path=_absolute_path(input_path),
            output_path=_absolute_path(output_path),
            cache_path=_absolute_path(cache_path),
            source=options.source,
            target=options.target,
            translator_name=translator_name,
            url=url,
            glossary_path=_absolute_path(glossary_path) if glossary_path else None,
            fail_fast=options.fail_fast,
            overwrite=overwrite,
            timeout=timeout,
            retries=retries,
            chunk_limit=options.chunk_limit,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_dict(cls, data: object) -> "TranslationResumeState":
        if not isinstance(data, dict):
            raise ResumeStateError("Resume state JSON must be an object.")

        version = _required_int(data, "version")
        if version != RESUME_STATE_VERSION:
            raise ResumeStateError(f"Unsupported resume state version: {version}.")

        status = _required_text(data, "status")
        if status not in (RUNNING_STATUS, COMPLETED_STATUS):
            raise ResumeStateError(f"Unsupported resume state status: {status}.")

        return cls(
            version=version,
            status=status,
            input_path=Path(_required_text(data, "input_path")),
            output_path=Path(_required_text(data, "output_path")),
            cache_path=Path(_required_text(data, "cache_path")),
            source=_required_text(data, "source"),
            target=_required_text(data, "target"),
            translator_name=_required_text(data, "translator_name"),
            url=_required_text(data, "url"),
            glossary_path=_optional_path(data, "glossary_path"),
            fail_fast=_required_bool(data, "fail_fast"),
            overwrite=_required_bool(data, "overwrite"),
            timeout=_required_number(data, "timeout"),
            retries=_required_int(data, "retries"),
            chunk_limit=_required_int(data, "chunk_limit"),
            created_at=_required_text(data, "created_at"),
            updated_at=_required_text(data, "updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("input_path", "output_path", "cache_path", "glossary_path"):
            value = data[key]
            data[key] = str(value) if value is not None else None
        return data

    def mark_completed(self) -> "TranslationResumeState":
        return replace(self, status=COMPLETED_STATUS, updated_at=_utc_now())


@dataclass(frozen=True)
class ResumeStateStore:
    processing_dir: Path

    def state_path_for(self, state: TranslationResumeState) -> Path:
        filename = f"{_safe_filename_part(state.input_path.stem)}-{_safe_filename_part(state.target)}.ayvu-state.json"
        return self.processing_dir / filename

    def save(self, state: TranslationResumeState) -> Path:
        self.processing_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_path_for(state)
        path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def load(self, path: Path) -> TranslationResumeState:
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except FileNotFoundError as exc:
            raise ResumeStateError(f"Resume state file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ResumeStateError(f"Resume state file is not valid JSON: {path}") from exc

        try:
            return TranslationResumeState.from_dict(data)
        except ResumeStateError as exc:
            raise ResumeStateError(f"Invalid resume state file {path}: {exc}") from exc


def default_processing_dir() -> Path:
    return Path.home() / "Documentos" / "Livros" / "Processando"


def _required_text(data: dict[str, object], key: str) -> str:
    value = _required_value(data, key)
    if not isinstance(value, str) or not value.strip():
        raise ResumeStateError(f"Resume state field {key} must be a non-empty string.")
    return value


def _required_int(data: dict[str, object], key: str) -> int:
    value = _required_value(data, key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResumeStateError(f"Resume state field {key} must be an integer.")
    return value


def _required_bool(data: dict[str, object], key: str) -> bool:
    value = _required_value(data, key)
    if not isinstance(value, bool):
        raise ResumeStateError(f"Resume state field {key} must be true or false.")
    return value


def _required_number(data: dict[str, object], key: str) -> float:
    value = _required_value(data, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResumeStateError(f"Resume state field {key} must be a number.")
    return float(value)


def _required_value(data: dict[str, object], key: str) -> object:
    if key not in data:
        raise ResumeStateError(f"Resume state field {key} is required.")
    return data[key]


def _optional_path(data: dict[str, object], key: str) -> Path | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ResumeStateError(f"Resume state field {key} must be a string or null.")
    return Path(value)


def _safe_filename_part(value: str) -> str:
    clean = []
    for char in value.strip():
        if char.isalnum() or char in ("-", "_"):
            clean.append(char)
            continue
        if char in (" ", "."):
            clean.append("-")

    filename = "".join(clean).strip("-_")
    return filename or "translation"


def _absolute_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
