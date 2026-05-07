from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .cache import TranslationCache
from .cli_progress import TranslationProgress
from .domain import LanguagePair, OutputPlan, TranslationOptions
from .epub_io import TranslationReport, extract_markdown, inspect_epub, translate_epub
from .preflight import PreflightError, run_translation_preflight
from .resume import (
    InvalidResumeState,
    ResumeStateError,
    ResumeStateScan,
    ResumeStateStore,
    TranslationResumeState,
    default_processing_dir,
)
from .translator import LibreTranslateTranslator, TranslatorError
from .validation import validate_output_epub


app = typer.Typer(help="Translate local EPUB files with a local HTTP translator.")
console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Translate local EPUB files with a local HTTP translator."""
    if ctx.invoked_subcommand is not None:
        return

    scan = _print_processing_translation_states(ResumeStateStore(default_processing_dir()))
    if _offer_detected_translation_resume(scan.running):
        return

    console.print(ctx.get_help())


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
    _run_translation(
        epub_path=epub_path,
        output=output,
        source=source,
        target=target,
        translator_name=translator_name,
        url=url,
        cache_path=cache_path,
        glossary_path=glossary_path,
        dry_run=dry_run,
        fail_fast=fail_fast,
        overwrite=overwrite,
        timeout=timeout,
        retries=retries,
        chunk_limit=chunk_limit,
    )


def _run_translation(
    epub_path: Path,
    output: Path | None,
    source: str,
    target: str,
    translator_name: str,
    url: str,
    cache_path: Path,
    glossary_path: Path | None,
    dry_run: bool,
    fail_fast: bool,
    overwrite: bool,
    timeout: float,
    retries: int,
    chunk_limit: int,
) -> None:
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
        preflight = run_translation_preflight(
            epub_path=epub_path,
            cache_path=cache_path,
            glossary_path=glossary_path,
            translator_name=translator_name,
            url=url,
            timeout=timeout,
            retries=retries,
            language_pair=language_pair,
            dry_run=dry_run,
        )
    except PreflightError as exc:
        console.print(f"[red]Environment check failed:[/red] {exc}")
        console.print(exc.next_step)
        raise typer.Exit(code=1) from exc

    resume_store: ResumeStateStore | None = None
    resume_state: TranslationResumeState | None = None
    if not dry_run:
        resume_store, resume_state = _save_running_resume_state(
            epub_path=epub_path,
            output_path=output_path,
            cache_path=cache_path,
            translator_name=translator_name,
            url=url,
            glossary_path=glossary_path,
            options=translation_options,
            overwrite=overwrite,
            timeout=timeout,
            retries=retries,
        )

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
                translator=preflight.translator,
                cache=cache,
                options=translation_options,
                glossary=preflight.glossary,
                on_chapter_start=progress_view.chapter_started,
                on_chapter_done=progress_view.chapter_done,
                on_text_processed=progress_view.text_processed,
            )

    _print_report(report, dry_run)
    _offer_markdown_report(report, dry_run)

    if not dry_run:
        validation = validate_output_epub(output_path)
        if validation.ok:
            console.print(f"[green]Validation OK:[/green] {validation.document_count} XHTML/HTML documents found.")
            if resume_store and resume_state:
                _mark_resume_state_completed(resume_store, resume_state)
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


def _print_report(report: TranslationReport, dry_run: bool) -> None:
    table = Table(title="Translation report")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Original EPUB", _display_optional_path(report.input_path))
    table.add_row("Detected language", report.detected_language or "-")
    table.add_row("Translated language", report.target_language or "-")
    table.add_row("Output", _report_output_value(report, dry_run))
    table.add_row("Chapters processed", str(report.chapters_processed))
    table.add_row("Texts translated", str(report.texts_translated))
    table.add_row("Texts from cache", str(report.texts_from_cache))
    table.add_row("Errors", str(len(report.errors)))
    console.print(table)

    for error in report.errors:
        console.print(f"[yellow]Error:[/yellow] {error}")


def _print_processing_translation_states(store: ResumeStateStore) -> ResumeStateScan:
    scan = store.scan()
    if not scan.has_findings:
        return scan

    if scan.running:
        _print_running_resume_states(scan.running)
    if scan.invalid:
        _print_invalid_resume_states(scan.invalid)
    return scan


def _offer_detected_translation_resume(states: tuple[TranslationResumeState, ...]) -> bool:
    if not states:
        return False
    if len(states) > 1:
        console.print("Multiple translations are in progress; automatic selection is not available yet.")
        return False

    state = states[0]
    if not typer.confirm("Continue detected translation?", default=False):
        console.print("Detected translation was not resumed. Processing files were left unchanged.")
        return False

    console.print(f"[green]Resuming translation:[/green] {state.input_path.name} -> {state.output_path.name}")
    _resume_translation(state)
    return True


def _resume_translation(state: TranslationResumeState) -> None:
    try:
        _run_translation(
            epub_path=state.input_path,
            output=state.output_path,
            source=state.source,
            target=state.target,
            translator_name=state.translator_name,
            url=state.url,
            cache_path=state.cache_path,
            glossary_path=state.glossary_path,
            dry_run=False,
            fail_fast=state.fail_fast,
            overwrite=state.overwrite,
            timeout=state.timeout,
            retries=state.retries,
            chunk_limit=state.chunk_limit,
        )
    except typer.Exit:
        console.print(
            "Could not resume detected translation. Check the message above and restart the translation if needed."
        )
        raise


def _print_running_resume_states(states: tuple[TranslationResumeState, ...]) -> None:
    console.print("[yellow]Translations in progress were found.[/yellow]")
    table = Table(title="Processing translations")
    table.add_column("Original EPUB")
    table.add_column("Output")
    table.add_column("Target")
    table.add_column("Cache")
    for state in states:
        table.add_row(
            state.input_path.name,
            state.output_path.name,
            state.target,
            state.cache_path.name,
        )
    console.print(table)


def _print_invalid_resume_states(states: tuple[InvalidResumeState, ...]) -> None:
    console.print("[yellow]Invalid processing state files were found.[/yellow]")
    table = Table(title="Invalid processing states")
    table.add_column("State file")
    table.add_column("Problem")
    for state in states:
        table.add_row(state.path.name, _single_line(state.message))
    console.print(table)
    console.print("Restart the translation if the state file cannot be fixed.")


def _save_running_resume_state(
    epub_path: Path,
    output_path: Path,
    cache_path: Path,
    translator_name: str,
    url: str,
    glossary_path: Path | None,
    options: TranslationOptions,
    overwrite: bool,
    timeout: float,
    retries: int,
) -> tuple[ResumeStateStore, TranslationResumeState]:
    store = ResumeStateStore(default_processing_dir())
    state = TranslationResumeState.create(
        input_path=epub_path,
        output_path=output_path,
        cache_path=cache_path,
        translator_name=translator_name,
        url=url,
        glossary_path=glossary_path,
        options=options,
        overwrite=overwrite,
        timeout=timeout,
        retries=retries,
    )
    _save_resume_state(store, state)
    return store, state


def _mark_resume_state_completed(store: ResumeStateStore, state: TranslationResumeState) -> None:
    _save_resume_state(store, state.mark_completed())


def _save_resume_state(store: ResumeStateStore, state: TranslationResumeState) -> None:
    try:
        store.save(state)
    except (OSError, ResumeStateError) as exc:
        console.print(f"[red]Resume state check failed:[/red] {exc}")
        console.print(
            "Choose a writable processing directory or fix permissions for Documentos/Livros/Processando."
        )
        raise typer.Exit(code=1) from exc


def _offer_markdown_report(report: TranslationReport, dry_run: bool) -> None:
    if not typer.confirm("Save translation report as Markdown?", default=False):
        return

    path = _save_markdown_report(report, dry_run)
    console.print(f"[green]Report saved to:[/green] {path}")


def _save_markdown_report(report: TranslationReport, dry_run: bool) -> Path:
    directory = _default_reports_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _next_available_report_path(directory, _report_filename_stem(report))
    path.write_text(_render_markdown_report(report, dry_run), encoding="utf-8")
    return path


def _render_markdown_report(report: TranslationReport, dry_run: bool) -> str:
    lines = [
        "# Translation report",
        "",
        f"- Original EPUB: {_display_optional_path(report.input_path)}",
        f"- Detected language: {report.detected_language or '-'}",
        f"- Translated language: {report.target_language or '-'}",
        f"- Output: {_report_output_value(report, dry_run)}",
        f"- Chapters processed: {report.chapters_processed}",
        f"- Texts translated: {report.texts_translated}",
        f"- Texts from cache: {report.texts_from_cache}",
        f"- Errors: {len(report.errors)}",
    ]

    if report.errors:
        lines.extend(["", "## Errors"])
        lines.extend(f"- {_single_line(error)}" for error in report.errors)

    return "\n".join(lines) + "\n"


def _default_reports_dir() -> Path:
    return Path.home() / "Documentos" / "Livros" / "Relatorios"


def _next_available_report_path(directory: Path, stem: str) -> Path:
    path = directory / f"{stem}.md"
    index = 2
    while path.exists():
        path = directory / f"{stem}-{index}.md"
        index += 1
    return path


def _report_filename_stem(report: TranslationReport) -> str:
    source = _safe_filename_part(report.input_path.stem if report.input_path else "translation")
    target = _safe_filename_part(report.target_language or "translated")
    return f"{source}-{target}-report"


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


def _display_optional_path(path: Path | None) -> str:
    if path is None:
        return "-"
    return str(path)


def _report_output_value(report: TranslationReport, dry_run: bool) -> str:
    if dry_run:
        return "(dry run, no file written)"
    return _display_optional_path(report.output_path)


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _confirm_existing_output_overwrite(output_path: Path) -> bool:
    console.print(f"[yellow]Output path:[/yellow] {output_path}")
    console.print("[yellow]Translated EPUB already exists.[/yellow]")
    return typer.confirm("Overwrite existing translated EPUB?", default=False)


if __name__ == "__main__":
    app()
