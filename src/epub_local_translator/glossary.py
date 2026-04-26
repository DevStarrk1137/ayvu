from __future__ import annotations

import json
import re
from pathlib import Path


Glossary = dict[str, str]


class GlossaryError(ValueError):
    pass


def load_glossary(path: str | Path | None) -> Glossary:
    if not path:
        return {}
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
    return {str(key): str(value) for key, value in data.items()}


def apply_glossary(text: str, glossary: Glossary | None) -> str:
    if not glossary:
        return text
    result = text
    for source_term, target_term in sorted(glossary.items(), key=lambda item: len(item[0]), reverse=True):
        if not source_term:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(source_term)}(?!\w)", re.IGNORECASE)
        result = pattern.sub(lambda match: _match_case(match.group(0), target_term), result)
    return result


def _match_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper() and original[1:].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement
