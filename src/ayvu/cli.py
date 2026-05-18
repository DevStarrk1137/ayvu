from __future__ import annotations

from pathlib import Path
from typing import NoReturn, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .cache import TranslationCache
from .cli_progress import TranslationProgress, TranslationProgressSnapshot
from .domain import (
    LanguagePair,
    OutputPlan,
    TranslationOptions,
    UserMode,
    default_preview_books_dir,
    default_translated_books_dir,
)
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
from .translator import LibreTranslateTranslator, TranslatorError, TranslatorLanguage
from .validation import validate_output_epub


app = typer.Typer(help="Translate local EPUB files with a local HTTP translator.")
console = Console()
DEFAULT_SOURCE_LANGUAGE = "en"
DEFAULT_TARGET_LANGUAGE = "pt"
DEFAULT_TRANSLATOR_URL = "http://localhost:5000"
DEFAULT_PREVIEW_DOCUMENT_LIMIT = 12
GUIDED_TRANSLATE_OPTION = "1"
GUIDED_PREVIEW_OPTION = "2"
GUIDED_LIBRARY_OPTION = "3"
GUIDED_SETTINGS_OPTION = "4"
GUIDED_HELP_OPTION = "5"
GUIDED_EXIT_OPTION = "0"
EXISTING_OUTPUT_OVERWRITE_OPTION = "1"
EXISTING_OUTPUT_RENAME_OPTION = "2"
EXISTING_OUTPUT_CANCEL_OPTION = "0"


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    mode: Optional[UserMode] = typer.Option(
        None,
        "--mode",
        help="Execution mode (common or developer). If not specified, it's inferred from usage.",
    ),
    preview: Optional[Path] = typer.Option(
        None,
        "--preview",
        help="Generate a translated EPUB preview with default settings.",
    ),
) -> None:
    """Translate local EPUB files with a local HTTP translator."""
    if mode is None:
        mode = UserMode.DEVELOPER
        # COMMON mode is only when running 'ayvu' without subcommands or options (except for help)
        # Typer sets invoked_subcommand when a subcommand is used.
        # ctx.params contains options of the callback itself.
        if ctx.invoked_subcommand is None and not any(v for k, v in ctx.params.items() if k != "mode"):
            mode = UserMode.COMMON
    ctx.ensure_object(dict)
    ctx.obj["mode"] = mode

    if ctx.invoked_subcommand is not None:
        return

    if preview is not None:
        _run_preview(preview, mode=mode)
        return

    scan = _print_processing_translation_states(ResumeStateStore(default_processing_dir()))
    if _offer_detected_translation_resume(scan.running, mode=mode):
        return

    if _run_guided_main_flow(ctx, mode=mode):
        return

    console.print(ctx.get_help())


@app.command()
def inspect(
    ctx: typer.Context,
    epub_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Show basic information about an EPUB."""
    mode = ctx.obj.get("mode", UserMode.DEVELOPER)
    try:
        info = inspect_epub(epub_path)
    except Exception as exc:
        _print_epub_read_error(str(exc), mode)
        raise typer.Exit(code=1) from exc
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
    ctx: typer.Context,
    url: str = typer.Option(DEFAULT_TRANSLATOR_URL, "--url", help="LibreTranslate base URL or /translate endpoint."),
    source: str = typer.Option(DEFAULT_SOURCE_LANGUAGE, "--source"),
    target: str = typer.Option(DEFAULT_TARGET_LANGUAGE, "--target"),
    timeout: float = typer.Option(10.0, "--timeout"),
    retries: int = typer.Option(1, "--retries"),
) -> None:
    """Test connectivity with the local translator."""
    mode = ctx.obj.get("mode", UserMode.DEVELOPER)
    translator = LibreTranslateTranslator(url=url, timeout=timeout, retries=retries)
    try:
        translated = translator.translate("Hello world", source, target)
    except TranslatorError as exc:
        _print_expected_error(
            "O teste do tradutor falhou.",
            "Inicie o LibreTranslate, verifique --url e tente novamente.",
            mode,
            detail=str(exc),
        )
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Translator OK:[/green] Hello world -> {translated}")


@app.command("languages")
def languages(
    ctx: typer.Context,
    url: str = typer.Option(DEFAULT_TRANSLATOR_URL, "--url", help="LibreTranslate base URL or /translate endpoint."),
    timeout: float = typer.Option(10.0, "--timeout"),
    retries: int = typer.Option(1, "--retries"),
) -> None:
    """List languages reported by the local LibreTranslate server."""
    mode = ctx.obj.get("mode", UserMode.DEVELOPER)
    translator = LibreTranslateTranslator(url=url, timeout=timeout, retries=retries)
    try:
        available_languages = translator.list_languages()
    except TranslatorError as exc:
        _print_expected_error(
            "Não foi possível listar os idiomas.",
            "Inicie o LibreTranslate, verifique --url e tente novamente.",
            mode,
            detail=str(exc),
        )
        raise typer.Exit(code=1) from exc

    _print_languages(available_languages)


@app.command()
def translate(
    ctx: typer.Context,
    epub_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output EPUB path. Defaults to <input-stem>-<target>.epub.",
    ),
    source: str = typer.Option(DEFAULT_SOURCE_LANGUAGE, "--source", help="Source language."),
    target: str = typer.Option(DEFAULT_TARGET_LANGUAGE, "--target", help="Target language."),
    translator_name: str = typer.Option("libretranslate", "--translator", help="Translator backend."),
    url: str = typer.Option(DEFAULT_TRANSLATOR_URL, "--url", help="Translator base URL."),
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
    mode = ctx.obj.get("mode", UserMode.DEVELOPER)
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
        mode=mode,
    )


def _print_expected_error(summary: str, next_step: str, mode: UserMode, detail: str = "") -> None:
    console.print(f"[red]{summary}[/red]")
    if mode == UserMode.DEVELOPER and detail:
        console.print(f"[dim]Detalhe técnico: {detail}[/dim]")
    console.print(next_step)


def _print_epub_read_error(detail: str, mode: UserMode) -> None:
    _print_expected_error(
        "Não foi possível ler o EPUB informado.",
        "Confirme que o arquivo é um EPUB válido e legível e tente novamente.",
        mode,
        detail=detail,
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
    mode: UserMode,
) -> None:
    language_pair = LanguagePair(source=source, target=target)
    translation_options = TranslationOptions(
        language_pair=language_pair,
        dry_run=dry_run,
        fail_fast=fail_fast,
        chunk_limit=chunk_limit,
    )
    output_plan = OutputPlan.for_translation(
        epub_path,
        output,
        language_pair,
        dry_run=dry_run,
        default_dir=default_translated_books_dir(),
    )
    output_plan = _confirm_default_output_location(output_plan, epub_path, mode=mode)
    output_plan = _resolve_existing_output_conflict(output_plan, overwrite=overwrite, mode=mode)
    output_path = output_plan.path

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
        _print_expected_error(exc.summary, exc.next_step, mode, detail=exc.detail)
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

    progress_view: TranslationProgress | None = None
    try:
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
    except KeyboardInterrupt as exc:
        _print_interrupted_translation(
            snapshot=progress_view.snapshot() if progress_view else None,
            output_path=output_path,
            cache_path=cache_path,
            dry_run=dry_run,
        )
        raise typer.Exit(code=1) from exc

    validation = None if dry_run else _validate_with_progress(output_path)
    validation_warnings = validation.warnings if validation else []

    _print_report(report, dry_run, validation_warnings)
    _offer_markdown_report(report, dry_run, validation_warnings, mode=mode)

    if validation is not None:
        if validation.ok:
            console.print(
                f"[green]Validação OK:[/green] {validation.document_count} documentos XHTML/HTML encontrados."
            )
            if resume_store and resume_state:
                _mark_resume_state_completed(resume_store, resume_state)
        else:
            raise typer.Exit(code=1)


def _run_preview(
    epub_path: Path,
    source: str = DEFAULT_SOURCE_LANGUAGE,
    target: str = DEFAULT_TARGET_LANGUAGE,
    translator_name: str = "libretranslate",
    url: str = DEFAULT_TRANSLATOR_URL,
    cache_path: Path = Path(".cache/traducoes.sqlite"),
    glossary_path: Path | None = None,
    timeout: float = 30.0,
    retries: int = 2,
    chunk_limit: int = 3000,
    max_documents: int = DEFAULT_PREVIEW_DOCUMENT_LIMIT,
    mode: UserMode = UserMode.DEVELOPER,
) -> None:
    epub_path = epub_path.expanduser()
    _ensure_preview_input_exists(epub_path)

    language_pair = LanguagePair(source=source, target=target)
    translation_options = TranslationOptions(
        language_pair=language_pair,
        chunk_limit=chunk_limit,
        max_documents=max_documents,
    )
    output_plan = OutputPlan.for_preview(
        epub_path,
        default_dir=default_preview_books_dir(),
    )
    output_path = output_plan.path
    _print_preview_output_location(output_path, max_documents)

    if output_plan.blocks_existing_file(overwrite=False):
        if not _confirm_existing_preview_overwrite(output_path, mode=mode):
            console.print("[red]Canceled:[/red] existing preview was not changed.")
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
            dry_run=False,
        )
    except PreflightError as exc:
        _print_expected_error(exc.summary, exc.next_step, mode, detail=exc.detail)
        raise typer.Exit(code=1) from exc

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        progress_view = TranslationProgress(progress, dry_run=False)
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

    validation = _validate_with_progress(output_path)
    _print_report(report, dry_run=False, validation_warnings=validation.warnings)
    if validation.ok:
        console.print(f"[green]Preview salvo em:[/green] {output_path}")
        console.print(
            f"[green]Validação OK:[/green] {validation.document_count} documentos XHTML/HTML encontrados."
        )
        return

    raise typer.Exit(code=1)


@app.command()
def extract(
    ctx: typer.Context,
    epub_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Path = typer.Option(..., "--output", "-o", help="Directory where Markdown files will be written."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow writing into an existing non-empty directory."),
) -> None:
    """Extract visible text from EPUB documents to Markdown files without translating."""
    mode = ctx.obj.get("mode", UserMode.DEVELOPER)
    if output.exists() and any(output.iterdir()) and not overwrite:
        console.print(f"[red]Output directory is not empty:[/red] {output}")
        console.print("Use --overwrite to write into it.")
        raise typer.Exit(code=1)
    try:
        written = extract_markdown(epub_path, output)
    except Exception as exc:
        _print_epub_read_error(str(exc), mode)
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Extracted {len(written)} Markdown files to[/green] {output}")


def _validate_with_progress(output_path: Path) -> ValidationResult:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Validando EPUB", total=None)

        def on_progress(index: int, total: int, _name: str) -> None:
            progress.update(
                task,
                total=total,
                completed=index,
                description=f"Validando EPUB {index}/{total}",
            )

        return validate_output_epub(output_path, on_progress=on_progress)


def _print_validation_warnings(warnings: list[str]) -> None:
    console.print("[yellow]Avisos de validação:[/yellow]")
    for warning in warnings:
        console.print(f"  - {warning}")


def _print_report(
    report: TranslationReport,
    dry_run: bool,
    validation_warnings: list[str] | None = None,
) -> None:
    validation_warnings = validation_warnings or []
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
    table.add_row("Validation warnings", str(len(validation_warnings)))
    console.print(table)

    for error in report.errors:
        console.print(f"[yellow]Error:[/yellow] {error}")

    if validation_warnings:
        _print_validation_warnings(validation_warnings)


def _print_interrupted_translation(
    snapshot: TranslationProgressSnapshot | None,
    output_path: Path,
    cache_path: Path,
    dry_run: bool,
) -> None:
    console.print("[yellow]Translation interrupted by user.[/yellow]")
    console.print("Cached translations saved before the interruption can be reused with the same --cache path.")
    console.print(f"Cache path: {cache_path}")
    console.print(_interrupted_output_message(output_path, dry_run))

    if snapshot is None:
        return

    table = Table(title="Partial translation progress")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Chapters processed", _partial_chapter_value(snapshot))
    table.add_row("Texts processed", str(snapshot.texts_processed))
    table.add_row("Texts translated", str(snapshot.texts_translated))
    table.add_row("Texts from cache", str(snapshot.texts_from_cache))
    table.add_row("Texts dry-run", str(snapshot.texts_dry_run))
    table.add_row("Text errors", str(snapshot.text_errors))
    table.add_row("Current chapter", snapshot.current_chapter or "-")
    console.print(table)


def _partial_chapter_value(snapshot: TranslationProgressSnapshot) -> str:
    if snapshot.total_chapters is None:
        return str(snapshot.chapters_processed)
    return f"{snapshot.chapters_processed}/{snapshot.total_chapters}"


def _interrupted_output_message(output_path: Path, dry_run: bool) -> str:
    if dry_run:
        return "Dry run interrupted; no translated EPUB was expected."
    if output_path.exists():
        return f"Translated EPUB may be incomplete: {output_path}"
    return f"Translated EPUB was not written: {output_path}"


def _print_processing_translation_states(store: ResumeStateStore) -> ResumeStateScan:
    scan = store.scan()
    if not scan.has_findings:
        return scan

    if scan.running:
        _print_running_resume_states(scan.running)
    if scan.invalid:
        _print_invalid_resume_states(scan.invalid)
    return scan


def _run_guided_main_flow(ctx: typer.Context, mode: UserMode) -> bool:
    if mode == UserMode.DEVELOPER:
        return False

    _print_guided_main_menu()
    choice = typer.prompt("Choose an option", default=GUIDED_PREVIEW_OPTION).strip()
    return _handle_guided_main_choice(choice, ctx)


def _print_guided_main_menu() -> None:
    table = Table(title="Ayvu")
    table.add_column("Option")
    table.add_column("Action")
    table.add_row(GUIDED_TRANSLATE_OPTION, "Translate a book")
    table.add_row(GUIDED_PREVIEW_OPTION, "Generate preview")
    table.add_row(GUIDED_LIBRARY_OPTION, "Open library")
    table.add_row(GUIDED_SETTINGS_OPTION, "Settings")
    table.add_row(GUIDED_HELP_OPTION, "Show command help")
    table.add_row(GUIDED_EXIT_OPTION, "Exit")
    console.print(table)


def _handle_guided_main_choice(choice: str, ctx: typer.Context) -> bool:
    if choice == GUIDED_TRANSLATE_OPTION:
        _run_guided_translation()
        return True

    if choice == GUIDED_PREVIEW_OPTION:
        _run_guided_preview()
        return True

    if choice == GUIDED_LIBRARY_OPTION:
        _print_guided_placeholder("Library")
        return True

    if choice == GUIDED_SETTINGS_OPTION:
        _print_guided_placeholder("Settings menu")
        return True

    if choice == GUIDED_HELP_OPTION:
        console.print(ctx.get_help())
        return True

    if choice == GUIDED_EXIT_OPTION:
        console.print("Canceled.")
        return True

    console.print("[red]Unknown option.[/red]")
    console.print(ctx.get_help())
    return True


def _run_guided_translation() -> None:
    epub_path = Path(typer.prompt("EPUB path")).expanduser()
    target = _choose_guided_target_language(DEFAULT_TARGET_LANGUAGE)
    _run_translation(
        epub_path=epub_path,
        output=None,
        source=DEFAULT_SOURCE_LANGUAGE,
        target=target,
        translator_name="libretranslate",
        url=DEFAULT_TRANSLATOR_URL,
        cache_path=Path(".cache/traducoes.sqlite"),
        glossary_path=None,
        dry_run=False,
        fail_fast=False,
        overwrite=False,
        timeout=30.0,
        retries=2,
        chunk_limit=3000,
        mode=UserMode.COMMON,
    )


def _run_guided_preview() -> None:
    epub_path = Path(typer.prompt("EPUB path")).expanduser()
    target = _choose_guided_target_language(DEFAULT_TARGET_LANGUAGE)
    _run_preview(epub_path, target=target, mode=UserMode.COMMON)


def _print_guided_placeholder(name: str) -> None:
    console.print(f"[yellow]{name} is not available yet.[/yellow]")
    console.print("Use the command help for the current technical commands.")


def _choose_guided_target_language(default_target: str) -> str:
    console.print(f"[yellow]Default target language:[/yellow] {default_target}")
    if typer.confirm("Use default target language?", default=True):
        return default_target

    available_languages = _load_languages_for_guided_selection()
    if available_languages:
        _print_languages(available_languages)
    else:
        console.print("Enter a language code manually.")

    target = typer.prompt("Target language code", default=default_target).strip()
    return target or default_target


def _load_languages_for_guided_selection() -> tuple[TranslatorLanguage, ...]:
    translator = LibreTranslateTranslator(url=DEFAULT_TRANSLATOR_URL, timeout=10.0, retries=1)
    try:
        return translator.list_languages()
    except TranslatorError as exc:
        console.print(f"[yellow]Could not list LibreTranslate languages:[/yellow] {exc}")
        return ()


def _print_languages(languages: tuple[TranslatorLanguage, ...]) -> None:
    table = Table(title="LibreTranslate languages")
    table.add_column("Language")
    table.add_column("Code")
    table.add_column("State")
    table.add_column("Targets")

    for language in languages:
        table.add_row(
            language.name,
            language.code,
            language.state,
            _display_language_targets(language.targets),
        )
    console.print(table)


def _display_language_targets(targets: tuple[str, ...]) -> str:
    if not targets:
        return "-"
    if len(targets) <= 8:
        return ", ".join(targets)
    first_targets = ", ".join(targets[:8])
    return f"{first_targets} (+{len(targets) - 8})"


def _offer_detected_translation_resume(states: tuple[TranslationResumeState, ...], mode: UserMode) -> bool:
    if not states:
        return False
    # In DEVELOPER mode, we don't resume automatically to avoid unexpected behavior.
    # The user should probably use a resume-specific command if we had one,
    # or just let the cache handle it.
    if mode == UserMode.DEVELOPER:
        return False

    if len(states) > 1:
        console.print("Multiple translations are in progress; automatic selection is not available yet.")
        return False

    state = states[0]
    if not typer.confirm("Continue detected translation?", default=False):
        console.print("Detected translation was not resumed. Processing files were left unchanged.")
        return False

    console.print(f"[green]Resuming translation:[/green] {state.input_path.name} -> {state.output_path.name}")
    _resume_translation(state, mode=mode)
    return True


def _resume_translation(state: TranslationResumeState, mode: UserMode) -> None:
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
            mode=mode,
        )
    except typer.Exit:
        console.print(
            "Não foi possível retomar a tradução detectada. Verifique a mensagem acima e reinicie a tradução se necessário."
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


def _offer_markdown_report(
    report: TranslationReport,
    dry_run: bool,
    validation_warnings: list[str] | None = None,
    mode: UserMode = UserMode.DEVELOPER,
) -> None:
    if mode == UserMode.DEVELOPER:
        return

    if not typer.confirm("Save translation report as Markdown?", default=False):
        return

    path = _save_markdown_report(report, dry_run, validation_warnings)
    console.print(f"[green]Report saved to:[/green] {path}")


def _save_markdown_report(
    report: TranslationReport,
    dry_run: bool,
    validation_warnings: list[str] | None = None,
) -> Path:
    directory = _default_reports_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _next_available_report_path(directory, _report_filename_stem(report))
    path.write_text(_render_markdown_report(report, dry_run, validation_warnings), encoding="utf-8")
    return path


def _render_markdown_report(
    report: TranslationReport,
    dry_run: bool,
    validation_warnings: list[str] | None = None,
) -> str:
    validation_warnings = validation_warnings or []
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
        f"- Validation warnings: {len(validation_warnings)}",
    ]

    if report.errors:
        lines.extend(["", "## Errors"])
        lines.extend(f"- {_single_line(error)}" for error in report.errors)

    if validation_warnings:
        lines.extend(["", "## Validation warnings"])
        lines.extend(f"- {_single_line(warning)}" for warning in validation_warnings)

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


def _ensure_preview_input_exists(epub_path: Path) -> None:
    if epub_path.is_file():
        return
    console.print(f"[red]Preview EPUB was not found:[/red] {epub_path}")
    console.print("Choose a valid local EPUB file.")
    raise typer.Exit(code=1)


def _print_preview_output_location(output_path: Path, max_documents: int) -> None:
    console.print(f"[yellow]Preview output folder:[/yellow] {output_path.parent}")
    console.print(f"[yellow]Preview EPUB name:[/yellow] {output_path.name}")
    console.print(f"Preview will translate up to {max_documents} EPUB documents.")


def _confirm_default_output_location(output_plan: OutputPlan, input_path: Path, mode: UserMode) -> OutputPlan:
    if output_plan.explicit_output or output_plan.dry_run or mode == UserMode.DEVELOPER:
        return output_plan

    output_path = output_plan.path
    console.print(f"[yellow]Default output folder:[/yellow] {output_path.parent}")
    console.print(f"[yellow]Translated EPUB name:[/yellow] {output_path.name}")
    console.print(_original_epub_location_message(input_path))

    if typer.confirm("Keep this output location?", default=True):
        return output_plan

    return output_plan.with_path(_prompt_output_path(output_path))


def _original_epub_location_message(input_path: Path) -> str:
    if input_path.parent.name == "Original":
        return f"Original EPUB stays in Original: {input_path}"
    return f"Original EPUB remains unchanged: {input_path}"


def _prompt_output_path(default_path: Path) -> Path:
    raw_path = typer.prompt("Output EPUB path", default=str(default_path))
    output_path = Path(raw_path).expanduser()
    if not output_path.name:
        console.print("[red]Canceled:[/red] output path was not changed.")
        raise typer.Exit(code=1)
    if output_path.suffix.lower() != ".epub":
        return output_path.with_suffix(".epub")
    return output_path


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _resolve_existing_output_conflict(output_plan: OutputPlan, overwrite: bool, mode: UserMode) -> OutputPlan:
    if not output_plan.blocks_existing_file(overwrite):
        return output_plan
    if mode == UserMode.DEVELOPER:
        _cancel_existing_output(output_plan.path)

    console.print(f"[yellow]Output path:[/yellow] {output_plan.path}")
    console.print("[yellow]Translated EPUB already exists.[/yellow]")
    action = _prompt_existing_output_action()
    if action == EXISTING_OUTPUT_OVERWRITE_OPTION:
        return output_plan
    if action == EXISTING_OUTPUT_RENAME_OPTION:
        return output_plan.with_path(_prompt_available_output_path(output_plan.path))

    _cancel_existing_output(output_plan.path)


def _prompt_existing_output_action() -> str:
    console.print(f"{EXISTING_OUTPUT_OVERWRITE_OPTION}. Overwrite existing EPUB")
    console.print(f"{EXISTING_OUTPUT_RENAME_OPTION}. Choose another name")
    console.print(f"{EXISTING_OUTPUT_CANCEL_OPTION}. Cancel")

    while True:
        action = typer.prompt("Choose an option", default=EXISTING_OUTPUT_RENAME_OPTION).strip()
        if action in {
            EXISTING_OUTPUT_OVERWRITE_OPTION,
            EXISTING_OUTPUT_RENAME_OPTION,
            EXISTING_OUTPUT_CANCEL_OPTION,
        }:
            return action
        console.print("[red]Invalid option.[/red] Choose 1, 2, or 0.")


def _prompt_available_output_path(default_path: Path) -> Path:
    while True:
        output_path = _prompt_output_path(default_path)
        if not output_path.exists():
            console.print(f"[green]Final output path:[/green] {output_path}")
            return output_path
        console.print(f"[red]Output path already exists:[/red] {output_path}")
        if not typer.confirm("Choose another output path?", default=True):
            _cancel_existing_output(output_path)


def _cancel_existing_output(output_path: Path) -> NoReturn:
    console.print("[red]Canceled:[/red] existing output was not changed.")
    console.print(f"[yellow]Output path:[/yellow] {output_path}")
    console.print("Use --overwrite to replace it or --output to choose another EPUB path.")
    raise typer.Exit(code=1)


def _confirm_existing_preview_overwrite(output_path: Path, mode: UserMode) -> bool:
    if mode == UserMode.DEVELOPER:
        return False

    console.print(f"[yellow]Preview output path:[/yellow] {output_path}")
    console.print("[yellow]Preview EPUB already exists.[/yellow]")
    return typer.confirm("Overwrite existing preview EPUB?", default=False)


if __name__ == "__main__":
    app()
