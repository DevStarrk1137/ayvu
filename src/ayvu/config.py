from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


CONFIG_VERSION = 1
DEFAULT_TARGET_LANGUAGE = "pt"
DEFAULT_BOOKS_DIR = "~/Documentos/Livros"
DEFAULT_CONFIG_DIR = "ayvu"
DEFAULT_CONFIG_FILE = "config.json"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class FolderNames:
    original: str = "Original"
    translated: str = "Traduzidos"
    preview: str = "Preview"
    reports: str = "Relatorios"
    processing: str = "Processando"

    @classmethod
    def from_dict(cls, data: object) -> "FolderNames":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ConfigError("Config field folders must be an object.")

        return cls(
            original=_folder_name(data, "original", cls.original),
            translated=_folder_name(data, "translated", cls.translated),
            preview=_folder_name(data, "preview", cls.preview),
            reports=_folder_name(data, "reports", cls.reports),
            processing=_folder_name(data, "processing", cls.processing),
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AyvuConfig:
    version: int = CONFIG_VERSION
    default_target_language: str = DEFAULT_TARGET_LANGUAGE
    books_dir: Path = Path(DEFAULT_BOOKS_DIR)
    folders: FolderNames = field(default_factory=FolderNames)
    reader_app: str | None = None

    @classmethod
    def default(cls) -> "AyvuConfig":
        return cls()

    @classmethod
    def from_dict(cls, data: object) -> "AyvuConfig":
        if not isinstance(data, dict):
            raise ConfigError("Config JSON must be an object.")

        version = _optional_int(data, "version", CONFIG_VERSION)
        if version != CONFIG_VERSION:
            raise ConfigError(f"Unsupported config version: {version}.")

        return cls(
            version=version,
            default_target_language=_optional_text(
                data,
                "default_target_language",
                DEFAULT_TARGET_LANGUAGE,
            ),
            books_dir=Path(_optional_text(data, "books_dir", DEFAULT_BOOKS_DIR)),
            folders=FolderNames.from_dict(data.get("folders")),
            reader_app=_optional_nullable_text(data, "reader_app"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "default_target_language": self.default_target_language,
            "books_dir": str(self.books_dir),
            "folders": self.folders.to_dict(),
            "reader_app": self.reader_app,
        }

    @property
    def resolved_books_dir(self) -> Path:
        return self.books_dir.expanduser()

    @property
    def original_dir(self) -> Path:
        return self.resolved_books_dir / self.folders.original

    @property
    def translated_dir(self) -> Path:
        return self.resolved_books_dir / self.folders.translated

    @property
    def preview_dir(self) -> Path:
        return self.resolved_books_dir / self.folders.preview

    @property
    def reports_dir(self) -> Path:
        return self.resolved_books_dir / self.folders.reports

    @property
    def processing_dir(self) -> Path:
        return self.resolved_books_dir / self.folders.processing


@dataclass(frozen=True)
class ConfigStore:
    path: Path

    @classmethod
    def default(cls) -> "ConfigStore":
        return cls(default_config_path())

    def load(self) -> AyvuConfig:
        if not self.path.exists():
            return AyvuConfig.default()

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config file is not valid JSON: {self.path}") from exc
        except OSError as exc:
            raise ConfigError(f"Could not read config file: {self.path}") from exc

        try:
            return AyvuConfig.from_dict(data)
        except ConfigError as exc:
            raise ConfigError(f"Invalid config file {self.path}: {exc}") from exc

    def save(self, config: AyvuConfig) -> Path:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise ConfigError(f"Could not write config file: {self.path}") from exc
        return self.path


def default_config_path(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    environment = os.environ if env is None else env
    config_home = environment.get("XDG_CONFIG_HOME")
    if config_home:
        base_dir = Path(config_home).expanduser()
    else:
        base_dir = (home or Path.home()) / ".config"
    return base_dir / DEFAULT_CONFIG_DIR / DEFAULT_CONFIG_FILE


def _optional_text(data: dict[str, object], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Config field {key} must be a non-empty string.")
    return value


def _optional_nullable_text(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Config field {key} must be a non-empty string or null.")
    return value


def _optional_int(data: dict[str, object], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"Config field {key} must be an integer.")
    return value


def _folder_name(data: dict[str, object], key: str, default: str) -> str:
    value = _optional_text(data, key, default)
    path = Path(value)
    if path.is_absolute() or path.name != value or "/" in value or "\\" in value:
        raise ConfigError(f"Config folder name {key} must be a folder name, not a path.")
    return value
