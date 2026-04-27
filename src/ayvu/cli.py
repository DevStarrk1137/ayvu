from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .cache import TranslationCache
from .epub_io import extract_markdown, inspect_epub, translate_epub
from .glossary import GlossaryError, load_glossary
from .translator import LibreTranslateTranslator, TranslatorError, create_translator
from .validation import validate_output_epub


app = typer.Typer(help="Translate local EPUB files with a local HTTP translator.")
console = Console()


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
    output_path = _resolve_output_path(epub_path, output, target)

    if output_path.exists() and not overwrite and not dry_run:
        console.print(f"[red]Output already exists:[/red] {output_path}")
        console.print("Use --overwrite to replace it.")
        raise typer.Exit(code=1)

    try:
        glossary = load_glossary(glossary_path)
    except GlossaryError as exc:
        console.print(f"[red]Glossary error:[/red] {exc}")
        console.print("Create the file, pass the correct path, or remove --glossary to run without one.")
        raise typer.Exit(code=1) from exc

    translator = create_translator(translator_name, url=url, timeout=timeout, retries=retries)

    counters = {"translated": 0, "cache": 0, "dry_run": 0, "error": 0}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        chapter_task = progress.add_task("Chapters", total=None)
        text_task = progress.add_task("Texts", total=None)

        def on_chapter_start(index: int, total: int, name: str) -> None:
            progress.update(
                chapter_task,
                total=total,
                description=f"Chapters {index}/{total}: {_shorten(name)}",
            )

        def on_chapter_done(index: int, total: int, name: str, _stats: object) -> None:
            progress.advance(chapter_task)
            progress.update(chapter_task, description=f"Chapters {index}/{total}: {_shorten(name)}")

        def on_text_processed(status: str) -> None:
            counters[status] = counters.get(status, 0) + 1
            processed = sum(counters.values())
            new_label = "would translate" if dry_run else "new"
            new_count = counters["dry_run"] if dry_run else counters["translated"]
            progress.advance(text_task)
            progress.update(
                text_task,
                description=(
                    f"Texts {processed} | {new_label} {new_count} | "
                    f"cache {counters['cache']} | errors {counters['error']}"
                ),
            )

        with TranslationCache(cache_path) as cache:
            report = translate_epub(
                epub_path,
                output_path,
                translator=translator,
                cache=cache,
                source=source,
                target=target,
                glossary=glossary,
                dry_run=dry_run,
                fail_fast=fail_fast,
                chunk_limit=chunk_limit,
                on_chapter_start=on_chapter_start,
                on_chapter_done=on_chapter_done,
                on_text_processed=on_text_processed,
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


def _shorten(text: str, max_length: int = 50) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _resolve_output_path(epub_path: Path, output: Optional[Path], target: str) -> Path:
    if output is not None:
        return output

    target_label = target.strip() or "translated"
    return epub_path.with_name(f"{epub_path.stem}-{target_label}.epub")


if __name__ == "__main__":
    app()
