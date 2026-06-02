from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path


GLOSSARY_RULE_PRESERVE = "preserve"
GLOSSARY_RULE_TRANSLATE = "translate"
GLOSSARY_RULE_FORBIDDEN = "forbidden"
GLOSSARY_RULES = {GLOSSARY_RULE_PRESERVE, GLOSSARY_RULE_TRANSLATE, GLOSSARY_RULE_FORBIDDEN}


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    term: str
    rule: str
    translation: str | None = None

    @property
    def replacement(self) -> str | None:
        if self.rule == GLOSSARY_RULE_TRANSLATE:
            return self.translation
        if self.rule == GLOSSARY_RULE_PRESERVE:
            return self.term
        return None


@dataclass(frozen=True, init=False)
class Glossary:
    entries: tuple[GlossaryEntry, ...]

    def __init__(
        self,
        entries: Mapping[str, str] | Iterable[GlossaryEntry] | None = None,
    ) -> None:
        if entries is None:
            parsed_entries: tuple[GlossaryEntry, ...] = ()
        elif isinstance(entries, Mapping):
            parsed_entries = tuple(
                GlossaryEntry(
                    term=str(term),
                    rule=GLOSSARY_RULE_TRANSLATE,
                    translation=str(translation),
                )
                for term, translation in entries.items()
            )
        else:
            parsed_entries = tuple(entries)
        object.__setattr__(self, "entries", parsed_entries)

    @property
    def terms(self) -> dict[str, str]:
        return {
            entry.term: replacement
            for entry in self.entries
            if (replacement := entry.replacement) is not None
        }

    def apply(self, text: str) -> str:
        replace_entries = [entry for entry in self._ordered_entries() if entry.replacement is not None]
        if not replace_entries:
            return text
        result = text
        for entry in replace_entries:
            if not entry.term or entry.replacement is None:
                continue
            pattern = _term_pattern(entry.term)
            result = pattern.sub(lambda match: _match_case(match.group(0), entry.replacement), result)
        return result

    def forbidden_terms_in(self, text: str) -> list[str]:
        return [
            entry.term
            for entry in self._ordered_entries()
            if entry.rule == GLOSSARY_RULE_FORBIDDEN and _term_pattern(entry.term).search(text)
        ]

    def _ordered_entries(self) -> list[GlossaryEntry]:
        return sorted(self.entries, key=lambda entry: len(entry.term), reverse=True)

    def __bool__(self) -> bool:
        return bool(self.entries)


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
    return Glossary(_parse_glossary_entries(data))


def apply_glossary(text: str, glossary: Glossary | Mapping[object, object] | None) -> str:
    if not glossary:
        return text
    if isinstance(glossary, Glossary):
        return glossary.apply(text)
    return Glossary(_parse_glossary_entries(glossary)).apply(text)


def _parse_glossary_entries(data: Mapping[object, object]) -> tuple[GlossaryEntry, ...]:
    return tuple(_parse_glossary_entry(str(term), value) for term, value in data.items())


def _parse_glossary_entry(term: str, value: object) -> GlossaryEntry:
    _validate_term(term)
    if isinstance(value, str):
        return GlossaryEntry(term=term, rule=GLOSSARY_RULE_TRANSLATE, translation=value)
    if not isinstance(value, dict):
        raise GlossaryError(
            f"Glossary entry for '{term}' must be a string translation or an object with a rule"
        )

    rule = value.get("rule")
    if not isinstance(rule, str):
        raise GlossaryError(f"Glossary entry for '{term}' must include a string rule")
    if rule not in GLOSSARY_RULES:
        allowed_rules = ", ".join(sorted(GLOSSARY_RULES))
        raise GlossaryError(f"Glossary entry for '{term}' uses unsupported rule '{rule}': {allowed_rules}")

    allowed_fields = {"rule", "translation"} if rule == GLOSSARY_RULE_TRANSLATE else {"rule"}
    unknown_fields = sorted(set(value) - allowed_fields)
    if unknown_fields:
        fields = ", ".join(unknown_fields)
        raise GlossaryError(f"Glossary entry for '{term}' has unsupported fields: {fields}")

    if rule == GLOSSARY_RULE_TRANSLATE:
        translation = value.get("translation")
        if not isinstance(translation, str):
            raise GlossaryError(
                f"Glossary entry for '{term}' with rule 'translate' must include a string translation"
            )
        return GlossaryEntry(term=term, rule=rule, translation=translation)

    return GlossaryEntry(term=term, rule=rule)


def _validate_term(term: str) -> None:
    if not term:
        raise GlossaryError("Glossary terms must not be empty")
    if term != term.strip():
        raise GlossaryError(f"Glossary term '{term}' must not start or end with whitespace")


def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def _match_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper() and original[1:].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement
