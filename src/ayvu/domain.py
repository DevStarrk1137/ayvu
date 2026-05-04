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

    @classmethod
    def for_translation(
        cls,
        input_path: Path,
        explicit_output: Path | None,
        language_pair: LanguagePair,
        dry_run: bool = False,
    ) -> "OutputPlan":
        if explicit_output is not None:
            return cls(path=explicit_output, dry_run=dry_run)

        output_path = input_path.with_name(f"{input_path.stem}-{language_pair.target_label}.epub")
        return cls(path=output_path, dry_run=dry_run)

    def blocks_existing_file(self, overwrite: bool) -> bool:
        if self.dry_run:
            return False
        if overwrite:
            return False
        return self.path.exists()


@dataclass(frozen=True)
class TranslationOptions:
    language_pair: LanguagePair
    dry_run: bool = False
    fail_fast: bool = False
    chunk_limit: int = 3000

    @property
    def source(self) -> str:
        return self.language_pair.source

    @property
    def target(self) -> str:
        return self.language_pair.target
