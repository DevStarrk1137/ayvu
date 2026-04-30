from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Glossary:
    terms: dict[str, str] = field(default_factory=dict)

    def apply(self, text: str) -> str:
        if not self.terms:
            return text
        result = text
        for source_term, target_term in self._ordered_terms():
            if not source_term:
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(source_term)}(?!\w)", re.IGNORECASE)
            result = pattern.sub(lambda match: _match_case(match.group(0), target_term), result)
        return result

    def _ordered_terms(self) -> list[tuple[str, str]]:
        return sorted(self.terms.items(), key=lambda item: len(item[0]), reverse=True)

    def __bool__(self) -> bool:
        return bool(self.terms)


class GlossaryError(ValueError):
    pass


def load_glossary(path: str | Path | None) -> Glossary:
    if not path:
        return Glossary()
    glossary_path = Path(path)
    if not glossary_path.exists():
        raise GlossaryError(f"Glossary file not found: {glossary_path}")
    if not glossary_path.is_file():
        raise GlossaryError(f"Glossary path is not a file: {glossary_path}")

    try:
        with glossary_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise GlossaryError(f"Glossary file is not valid JSON: {glossary_path}") from exc

    if not isinstance(data, dict):
        raise GlossaryError("Glossary JSON must be an object mapping terms to translations")
    return Glossary({str(key): str(value) for key, value in data.items()})


def apply_glossary(text: str, glossary: Glossary | dict[str, str] | None) -> str:
    if not glossary:
        return text
    if isinstance(glossary, Glossary):
        return glossary.apply(text)
    return Glossary({str(key): str(value) for key, value in glossary.items()}).apply(text)


def _match_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper() and original[1:].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement
