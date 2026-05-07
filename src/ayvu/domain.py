from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class LanguagePairError(ValueError):
    pass


@dataclass(frozen=True)
class LanguagePair:
    source: str
    target: str

    @property
    def target_label(self) -> str:
        return self.target.strip() or "translated"

    def validate_for_translation(self) -> None:
        if not self.source.strip():
            raise LanguagePairError("source language is required")
        if not self.target.strip():
            raise LanguagePairError("target language is required")


@dataclass(frozen=True)
class OutputPlan:
    path: Path
    dry_run: bool = False
    explicit_output: bool = False

    @classmethod
    def for_translation(
        cls,
        input_path: Path,
        explicit_output: Path | None,
        language_pair: LanguagePair,
        dry_run: bool = False,
        default_dir: Path | None = None,
    ) -> "OutputPlan":
        if explicit_output is not None:
            return cls(path=explicit_output, dry_run=dry_run, explicit_output=True)

        output_dir = default_dir or default_translated_books_dir()
        output_path = output_dir / f"{input_path.stem}-{language_pair.target_label}.epub"
        return cls(path=output_path, dry_run=dry_run)

    @classmethod
    def for_preview(
        cls,
        input_path: Path,
        explicit_output: Path | None = None,
        default_dir: Path | None = None,
    ) -> "OutputPlan":
        if explicit_output is not None:
            return cls(path=explicit_output, explicit_output=True)

        output_dir = default_dir or default_preview_books_dir()
        return cls(path=output_dir / f"{input_path.stem}-preview.epub")

    def with_path(self, path: Path) -> "OutputPlan":
        return OutputPlan(path=path, dry_run=self.dry_run, explicit_output=self.explicit_output)

    def blocks_existing_file(self, overwrite: bool) -> bool:
        if self.dry_run:
            return False
        if overwrite:
            return False
        return self.path.exists()


def default_translated_books_dir() -> Path:
    return Path.home() / "Documentos" / "Livros" / "Traduzidos"


def default_preview_books_dir() -> Path:
    return Path.home() / "Documentos" / "Livros" / "Preview"


@dataclass(frozen=True)
class TranslationOptions:
    language_pair: LanguagePair
    dry_run: bool = False
    fail_fast: bool = False
    chunk_limit: int = 3000
    max_documents: int | None = None

    @property
    def source(self) -> str:
        return self.language_pair.source

    @property
    def target(self) -> str:
        return self.language_pair.target
