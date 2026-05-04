from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .cache import TranslationCache
from .domain import LanguagePair, OutputPlan, TranslationOptions
from .epub_io import extract_markdown, inspect_epub, translate_epub
from .glossary import GlossaryError, load_glossary
from .translator import LibreTranslateTranslator, TranslatorError, create_translator
from .validation import validate_output_epub


app = typer.Typer(help="Translate local EPUB files with a local HTTP translator.")
console = Console()


@dataclass
class TextProgressCounters:
    translated: int = 0
    cache: int = 0
    dry_run: int = 0
    error: int = 0

    def record(self, status: str) -> None:
        if status == "translated":
            self.translated += 1
            return
        if status == "cache":
            self.cache += 1
            return
        if status == "dry_run":
            self.dry_run += 1
            return
        if status == "error":
            self.error += 1
            return
        raise ValueError(f"Unknown text progress status: {status}")

    @property
    def processed(self) -> int:
        return self.translated + self.cache + self.dry_run + self.error

    def new_count(self, dry_run: bool) -> int:
        if dry_run:
            return self.dry_run
        return self.translated


class TranslationProgress:
    def __init__(self, progress: Progress, dry_run: bool) -> None:
        self._progress = progress
        self._dry_run = dry_run
        self._counters = TextProgressCounters()
        self._chapter_task = progress.add_task("Chapters", total=None)
        self._text_task = progress.add_task("Texts", total=None)

    def chapter_started(self, index: int, total: int, name: str) -> None:
        self._progress.update(
            self._chapter_task,
            total=total,
            description=self._chapter_description(index, total, name),
        )

    def chapter_done(self, index: int, total: int, name: str, _stats: object) -> None:
        self._progress.advance(self._chapter_task)
        self._progress.update(self._chapter_task, description=self._chapter_description(index, total, name))

    def text_processed(self, status: str) -> None:
        self._counters.record(status)
        self._progress.advance(self._text_task)
        self._progress.update(self._text_task, description=self._text_description())

    def _chapter_description(self, index: int, total: int, name: str) -> str:
        return f"Chapters {index}/{total}: {_shorten(name)}"

    def _text_description(self) -> str:
        new_label = "would translate" if self._dry_run else "new"
        new_count = self._counters.new_count(self._dry_run)
        return (
            f"Texts {self._counters.processed} | {new_label} {new_count} | "
            f"cache {self._counters.cache} | errors {self._counters.error}"
        )


@app.command()
def inspect(epub_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True)) -> None:
    """Show basic information about an EPUB."""
    info = inspect_epub(epub_path)
    table = Table(title="EPUB information")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Path", str(info.path))
    table.add_row("Title", info.title or "-")
    table.add_row("Authors", ", ".join(info.authors) if info.authors else "-")
    table.add_row("Language", info.language or "-")
    table.add_row("Documents", str(info.document_count))
    table.add_row("Items", str(info.item_count))
    console.print(table)


@app.command("test-translator")
def test_translator(
    url: str = typer.Option("http://localhost:5000", "--url", help="LibreTranslate base URL or /translate endpoint."),
    source: str = typer.Option("en", "--source"),
    target: str = typer.Option("pt", "--target"),
    timeout: float = typer.Option(10.0, "--timeout"),
    retries: int = typer.Option(1, "--retries"),
) -> None:
    """Test connectivity with the local translator."""
    translator = LibreTranslateTranslator(url=url, timeout=timeout, retries=retries)
    try:
        translated = translator.translate("Hello world", source, target)
    except TranslatorError as exc:
        console.print(f"[red]Translator test failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Translator OK:[/green] Hello world -> {translated}")


@app.command()
def translate(
    epub_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output EPUB path. Defaults to <input-stem>-<target>.epub.",
    ),
    source: str = typer.Option("en", "--source", help="Source language."),
    target: str = typer.Option("pt", "--target", help="Target language."),
    translator_name: str = typer.Option("libretranslate", "--translator", help="Translator backend."),
    url: str = typer.Option("http://localhost:5000", "--url", help="Translator base URL."),
    cache_path: Path = typer.Option(Path(".cache/traducoes.sqlite"), "--cache", help="SQLite cache path."),
    glossary_path: Optional[Path] = typer.Option(None, "--glossary", help="Optional JSON glossary."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Process without writing translated EPUB."),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop at the first chapter/text error."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow replacing an existing output file."),
    timeout: float = typer.Option(30.0, "--timeout", help="Translator HTTP timeout in seconds."),
    retries: int = typer.Option(2, "--retries", help="Simple HTTP retry count."),
    chunk_limit: int = typer.Option(3000, "--chunk-limit", help="Maximum characters sent per request."),
) -> None:
    """Translate EPUB visible text while preserving EPUB structure."""
    language_pair = LanguagePair(source=source, target=target)
    translation_options = TranslationOptions(
        language_pair=language_pair,
        dry_run=dry_run,
        fail_fast=fail_fast,
        chunk_limit=chunk_limit,
    )
    output_plan = OutputPlan.for_translation(epub_path, output, language_pair, dry_run=dry_run)
    output_path = output_plan.path

    if output_plan.blocks_existing_file(overwrite):
        if not _confirm_existing_output_overwrite(output_path):
            console.print("[red]Canceled:[/red] existing output was not changed.")
            raise typer.Exit(code=1)

    try:
        glossary = load_glossary(glossary_path)
    except GlossaryError as exc:
        console.print(f"[red]Glossary error:[/red] {exc}")
        console.print("Create the file, pass the correct path, or remove --glossary to run without one.")
        raise typer.Exit(code=1) from exc

    try:
        translator = create_translator(translator_name, url=url, timeout=timeout, retries=retries)
    except TranslatorError as exc:
        console.print(f"[red]Translator error:[/red] {exc}")
        console.print("Use --translator libretranslate.")
        raise typer.Exit(code=1) from exc

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        progress_view = TranslationProgress(progress, dry_run=dry_run)

        with TranslationCache(cache_path) as cache:
            report = translate_epub(
                epub_path,
                output_path,
                translator=translator,
                cache=cache,
                options=translation_options,
                glossary=glossary,
                on_chapter_start=progress_view.chapter_started,
                on_chapter_done=progress_view.chapter_done,
                on_text_processed=progress_view.text_processed,
            )

    _print_report(
        report.chapters_processed,
        report.texts_translated,
        report.texts_from_cache,
        report.errors,
        output_path,
        dry_run,
    )

    if not dry_run:
        validation = validate_output_epub(output_path)
        if validation.ok:
            console.print(f"[green]Validation OK:[/green] {validation.document_count} XHTML/HTML documents found.")
        else:
            for warning in validation.warnings:
                console.print(f"[yellow]Warning:[/yellow] {warning}")
            raise typer.Exit(code=1)


@app.command()
def extract(
    epub_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Path = typer.Option(..., "--output", "-o", help="Directory where Markdown files will be written."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow writing into an existing non-empty directory."),
) -> None:
    """Extract visible text from EPUB documents to Markdown files without translating."""
    if output.exists() and any(output.iterdir()) and not overwrite:
        console.print(f"[red]Output directory is not empty:[/red] {output}")
        console.print("Use --overwrite to write into it.")
        raise typer.Exit(code=1)
    written = extract_markdown(epub_path, output)
    console.print(f"[green]Extracted {len(written)} Markdown files to[/green] {output}")


def _print_report(
    chapters_processed: int,
    translated: int,
    from_cache: int,
    errors: list[str],
    output: Path,
    dry_run: bool,
) -> None:
    table = Table(title="Translation report")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Chapters processed", str(chapters_processed))
    table.add_row("Texts translated", str(translated))
    table.add_row("Texts from cache", str(from_cache))
    table.add_row("Errors", str(len(errors)))
    table.add_row("Output", str(output) if not dry_run else "(dry run, no file written)")
    console.print(table)

    for error in errors:
        console.print(f"[yellow]Error:[/yellow] {error}")


def _confirm_existing_output_overwrite(output_path: Path) -> bool:
    console.print(f"[yellow]Output path:[/yellow] {output_path}")
    console.print("[yellow]Translated EPUB already exists.[/yellow]")
    return typer.confirm("Overwrite existing translated EPUB?", default=False)


def _shorten(text: str, max_length: int = 50) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


if __name__ == "__main__":
    app()
