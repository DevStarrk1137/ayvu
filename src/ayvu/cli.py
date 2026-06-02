from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import NoReturn, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .cache import TranslationCache
from .cli_progress import TranslationProgress, TranslationProgressSnapshot
from .config import DEFAULT_BOOKS_DIR, AyvuConfig, ConfigError, ConfigStore, FolderNames
from .domain import (
    LanguagePair,
    OutputPlan,
    TranslationOptions,
    UserMode,
    default_preview_books_dir,
    default_translated_books_dir,
)
from .epub_io import TranslationReport, detect_epub_language, extract_markdown, inspect_epub, translate_epub
from .library import LibraryBook, LibraryOpenError, open_library_epub, scan_library
from .preflight import PreflightError, run_translation_preflight
from .resume import (
    InvalidResumeState,
    ResumeStateError,
    ResumeStateScan,
    ResumeStateStore,
    TranslationResumeState,
    default_processing_dir,
)
from .translator import LibreTranslateTranslator, TranslationRoute, TranslatorError, TranslatorLanguage
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
GUIDED_DEFAULT_LANGUAGE_OPTION = "1"
GUIDED_OTHER_LANGUAGE_OPTION = "2"
LIBRARY_BACK_OPTION = "0"
SETTINGS_LANGUAGE_OPTION = "1"
SETTINGS_BOOKS_DIR_OPTION = "2"
SETTINGS_FOLDERS_OPTION = "3"
SETTINGS_READER_OPTION = "4"
SETTINGS_EXIT_OPTION = "0"
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

    config = _load_existing_config_or_default()
    scan = _print_processing_translation_states(ResumeStateStore(_processing_dir(config)))
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
    source: Optional[str] = typer.Option(
        None,
        "--source",
        help="Source language. If omitted, Ayvu reads the language metadata from the EPUB.",
    ),
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
    config = _load_existing_config_or_default()
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
        config=config,
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


def _resolve_source_language(
    explicit_source: str | None,
    epub_path: Path,
    mode: UserMode,
) -> tuple[str, bool]:
    if explicit_source is not None and explicit_source.strip():
        return explicit_source.strip(), False

    try:
        detected = detect_epub_language(epub_path)
    except Exception:
        return DEFAULT_SOURCE_LANGUAGE, True

    if detected is None:
        console.print(
            "[yellow]Idioma do EPUB ausente ou inválido nos metadados.[/yellow] "
            f"Usando '{DEFAULT_SOURCE_LANGUAGE}' como padrão. "
            "Use --source para escolher outro idioma de origem."
        )
        return DEFAULT_SOURCE_LANGUAGE, True

    return detected, True


def _print_translation_plan(
    language_pair: LanguagePair,
    source_inferred: bool,
    mode: UserMode,
) -> None:
    table = Table(title="Translation plan")
    table.add_column("Field")
    table.add_column("Value")
    source_value = language_pair.source
    if source_inferred and mode == UserMode.DEVELOPER:
        source_value = f"{language_pair.source} (inferido do EPUB)"
    table.add_row("From", source_value)
    table.add_row("To", language_pair.target)
    console.print(table)
    if source_inferred and mode == UserMode.COMMON:
        console.print(f"[dim]Idioma de origem detectado do EPUB: {language_pair.source}[/dim]")


def _print_translation_route(route: TranslationRoute | None, mode: UserMode) -> None:
    if route is None:
        return
    if mode == UserMode.DEVELOPER:
        console.print(f"[cyan]Route:[/cyan] {route.describe()}")
    if route.is_direct:
        return
    if mode == UserMode.COMMON:
        console.print(f"[yellow]A tradução passará por 2 etapas ({route.describe()}).[/yellow]")
        console.print("[yellow]A qualidade pode ficar comprometida por causa do idioma intermediário.[/yellow]")
    else:
        console.print("[yellow]Rota intermediária em uso. A qualidade pode ficar comprometida.[/yellow]")


def _run_translation(
    epub_path: Path,
    output: Path | None,
    source: str | None,
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
    config: AyvuConfig | None = None,
) -> None:
    config = config or _load_existing_config_or_default()
    resolved_source, source_inferred = _resolve_source_language(source, epub_path, mode=mode)
    language_pair = LanguagePair(source=resolved_source, target=target)
    _print_translation_plan(language_pair, source_inferred=source_inferred, mode=mode)
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
        default_dir=_translated_books_dir(config),
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

    _print_translation_route(preflight.route, mode=mode)

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
            processing_dir=_processing_dir(config),
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
    config: AyvuConfig | None = None,
) -> None:
    config = config or _load_existing_config_or_default()
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
        default_dir=_preview_books_dir(config),
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

    _print_translation_route(preflight.route, mode=mode)

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
    if _has_glossary_summary(report):
        table.add_row("Glossary terms configured", str(report.glossary_terms_configured))
        table.add_row("Glossary terms applied", str(report.glossary_usage.total_applied))
        table.add_row(
            "Required glossary terms missing",
            str(len(report.glossary_usage.required_terms_missing)),
        )
        table.add_row(
            "Forbidden glossary terms found",
            str(report.glossary_usage.total_forbidden_found),
        )
    console.print(table)

    for error in report.errors:
        console.print(f"[yellow]Error:[/yellow] {error}")

    _print_glossary_warnings(report)

    if validation_warnings:
        _print_validation_warnings(validation_warnings)


def _has_glossary_summary(report: TranslationReport) -> bool:
    return report.glossary_terms_configured > 0 or report.glossary_usage.has_activity


def _print_glossary_warnings(report: TranslationReport) -> None:
    usage = report.glossary_usage
    if not usage.required_terms_missing and not usage.forbidden_terms_found:
        return

    console.print("[yellow]Glossary warnings:[/yellow]")
    if usage.required_terms_missing:
        console.print(f"  - Required terms missing: {_format_terms(usage.required_terms_missing)}")
    if usage.forbidden_terms_found:
        console.print(f"  - Forbidden terms found: {_format_counted_terms(usage.forbidden_terms_found)}")


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

    config = _load_or_init_config()
    _print_guided_main_menu()
    choice = typer.prompt("Choose an option", default=GUIDED_PREVIEW_OPTION).strip()
    return _handle_guided_main_choice(choice, ctx, config)


def _load_or_init_config(store: ConfigStore | None = None) -> AyvuConfig:
    store = store or ConfigStore.default()
    if not store.path.exists():
        return _init_default_language_config(store)

    try:
        return store.load()
    except ConfigError as exc:
        console.print(f"[yellow]Configuração inválida ignorada:[/yellow] {exc}")
        console.print("Usando configuração padrão. Ajuste o arquivo de configuração se quiser alterar o idioma.")
        return AyvuConfig.default()


def _load_existing_config_or_default(store: ConfigStore | None = None) -> AyvuConfig:
    store = store or ConfigStore.default()
    try:
        return store.load()
    except ConfigError as exc:
        console.print(f"[yellow]Configuração inválida ignorada:[/yellow] {exc}")
        console.print("Usando configuração padrão. Ajuste o arquivo de configuração quando possível.")
        return AyvuConfig.default()


def _init_default_language_config(store: ConfigStore) -> AyvuConfig:
    console.print("[yellow]Primeiro uso do modo comum.[/yellow]")
    console.print("Escolha o idioma padrão de leitura/tradução. Você poderá alterá-lo depois em Settings.")
    language = _prompt_target_language_code(DEFAULT_TARGET_LANGUAGE)
    console.print(
        "Escolha a pasta base dos livros. "
        "O Ayvu usará essa pasta para biblioteca, previews, relatórios e traduções."
    )
    books_dir = _prompt_path("Books folder", Path(DEFAULT_BOOKS_DIR))
    folders = _choose_initial_folder_names(books_dir)
    config = AyvuConfig(
        default_target_language=language,
        books_dir=books_dir,
        folders=folders,
    )
    if _save_config(store, config):
        console.print(f"[green]Idioma padrão salvo:[/green] {language}")
        console.print(f"[green]Pasta base salva:[/green] {books_dir}")
    return config


def _choose_initial_folder_names(books_dir: Path) -> FolderNames:
    config = AyvuConfig(books_dir=books_dir)
    console.print("O Ayvu usará estes nomes de pastas por padrão:")
    _print_feature_folder_paths(config)
    if typer.confirm("Manter estes nomes de pastas?", default=True):
        return config.folders

    updated = _settings_with_folder_names(config)
    _print_feature_folder_paths(updated)
    return updated.folders


def _print_feature_folder_paths(config: AyvuConfig) -> None:
    table = Table(title="Feature folders")
    table.add_column("Feature")
    table.add_column("Folder")
    table.add_row("Original books", str(config.original_dir))
    table.add_row("Translated books", str(config.translated_dir))
    table.add_row("Previews", str(config.preview_dir))
    table.add_row("Reports", str(config.reports_dir))
    table.add_row("Processing states", str(config.processing_dir))
    console.print(table)


def _save_config(store: ConfigStore, config: AyvuConfig) -> bool:
    try:
        store.save(config)
        return True
    except ConfigError as exc:
        console.print(f"[yellow]Não foi possível salvar a configuração:[/yellow] {exc}")
        console.print("A mudança será usada nesta execução, mas não foi persistida.")
        return False


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


def _handle_guided_main_choice(choice: str, ctx: typer.Context, config: AyvuConfig) -> bool:
    if choice == GUIDED_TRANSLATE_OPTION:
        _run_guided_translation(config)
        return True

    if choice == GUIDED_PREVIEW_OPTION:
        _run_guided_preview(config)
        return True

    if choice == GUIDED_LIBRARY_OPTION:
        _run_guided_library(config)
        return True

    if choice == GUIDED_SETTINGS_OPTION:
        _run_guided_settings(config)
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


def _run_guided_translation(config: AyvuConfig) -> None:
    epub_path = Path(typer.prompt("EPUB path")).expanduser()
    target = _choose_guided_target_language(config.default_target_language)
    _run_translation(
        epub_path=epub_path,
        output=None,
        source=None,
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
        config=config,
    )


def _run_guided_preview(config: AyvuConfig) -> None:
    epub_path = Path(typer.prompt("EPUB path")).expanduser()
    target = _choose_guided_target_language(config.default_target_language)
    _run_preview(epub_path, target=target, mode=UserMode.COMMON, config=config)


def _run_guided_library(config: AyvuConfig) -> None:
    books = scan_library(config)
    if not books:
        console.print("[yellow]Library has no EPUB books yet.[/yellow]")
        console.print(f"Original folder: {config.original_dir}")
        console.print(f"Translated folder: {config.translated_dir}")
        return

    _print_library_books(books)
    book = _prompt_library_book(books)
    if book is None:
        return
    _run_guided_library_book(config, book)


def _print_library_books(books: tuple[LibraryBook, ...]) -> None:
    table = Table(title="Library")
    table.add_column("Option")
    table.add_column("Book")
    table.add_column("Original")
    table.add_column("Translations")

    for index, book in enumerate(books, start=1):
        table.add_row(
            str(index),
            book.name,
            "yes" if book.has_original else "-",
            _display_book_translations(book),
        )
    console.print(table)
    console.print(f"{LIBRARY_BACK_OPTION}. Back")


def _prompt_library_book(books: tuple[LibraryBook, ...]) -> LibraryBook | None:
    while True:
        choice = typer.prompt("Choose a book", default=LIBRARY_BACK_OPTION).strip()
        if choice == LIBRARY_BACK_OPTION:
            console.print("Library closed.")
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(books):
            return books[int(choice) - 1]
        console.print(f"[red]Invalid book.[/red] Choose 1-{len(books)} or 0.")


def _run_guided_library_book(config: AyvuConfig, book: LibraryBook) -> None:
    while True:
        actions = _library_book_actions(book)
        _print_library_book_actions(book, actions)
        choice = typer.prompt("Choose a library action", default=LIBRARY_BACK_OPTION).strip()
        if choice == LIBRARY_BACK_OPTION:
            console.print("Back to library.")
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(actions):
            console.print(f"[red]Invalid action.[/red] Choose 1-{len(actions)} or 0.")
            continue

        label, path = actions[int(choice) - 1]
        if path is None:
            _print_library_book_info(book)
            continue
        _open_library_book_path(path, config, label)
        return


def _library_book_actions(book: LibraryBook) -> list[tuple[str, Path | None]]:
    actions: list[tuple[str, Path | None]] = []
    if book.original_path:
        actions.append(("Open original", book.original_path))
    for translation in book.translations:
        actions.append((f"Open {translation.label}", translation.path))
    actions.append(("Show information", None))
    return actions


def _print_library_book_actions(book: LibraryBook, actions: list[tuple[str, Path | None]]) -> None:
    table = Table(title=book.name)
    table.add_column("Option")
    table.add_column("Action")
    for index, action in enumerate(actions, start=1):
        table.add_row(str(index), action[0])
    console.print(table)
    console.print(f"{LIBRARY_BACK_OPTION}. Back")


def _print_library_book_info(book: LibraryBook) -> None:
    table = Table(title="Book information")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Book", book.name)
    table.add_row("Original EPUB", str(book.original_path) if book.original_path else "-")
    table.add_row("Translations", _display_book_translations(book))
    table.add_row("Translation files", _display_translation_paths(book))
    console.print(table)


def _open_library_book_path(path: Path, config: AyvuConfig, label: str) -> None:
    try:
        open_library_epub(path, reader_app=config.reader_app)
    except LibraryOpenError as exc:
        console.print(f"[red]Could not open EPUB:[/red] {exc}")
        console.print("Configure Reader app in Settings or install a default EPUB reader.")
        return

    console.print(f"[green]{label}:[/green] {path}")


def _display_book_translations(book: LibraryBook) -> str:
    if not book.translations:
        return "-"
    return ", ".join(translation.label for translation in book.translations)


def _display_translation_paths(book: LibraryBook) -> str:
    if not book.translations:
        return "-"
    return "\n".join(str(translation.path) for translation in book.translations)


def _run_guided_settings(config: AyvuConfig) -> None:
    store = ConfigStore.default()
    current = config
    while True:
        _print_settings(current)
        _print_settings_menu()
        choice = typer.prompt("Choose a setting", default=SETTINGS_EXIT_OPTION).strip()
        if choice == SETTINGS_LANGUAGE_OPTION:
            current = _update_guided_settings(store, current, _settings_with_default_language(current))
            continue
        if choice == SETTINGS_BOOKS_DIR_OPTION:
            current = _update_guided_settings(store, current, _settings_with_books_dir(current))
            continue
        if choice == SETTINGS_FOLDERS_OPTION:
            current = _update_guided_settings(store, current, _settings_with_folder_names(current))
            continue
        if choice == SETTINGS_READER_OPTION:
            current = _update_guided_settings(store, current, _settings_with_reader_app(current))
            continue
        if choice == SETTINGS_EXIT_OPTION:
            console.print("Settings closed.")
            return

        console.print("[red]Invalid setting.[/red] Choose 1, 2, 3, 4, or 0.")


def _print_settings(config: AyvuConfig) -> None:
    table = Table(title="Settings")
    table.add_column("Preference")
    table.add_column("Current value")
    table.add_row("Default target language", config.default_target_language)
    table.add_row("Books folder", str(config.books_dir))
    table.add_row("Original folder", config.folders.original)
    table.add_row("Translated folder", config.folders.translated)
    table.add_row("Preview folder", config.folders.preview)
    table.add_row("Reports folder", config.folders.reports)
    table.add_row("Processing folder", config.folders.processing)
    table.add_row("Reader app", config.reader_app or "-")
    console.print(table)


def _print_settings_menu() -> None:
    console.print(f"{SETTINGS_LANGUAGE_OPTION}. Change default language")
    console.print(f"{SETTINGS_BOOKS_DIR_OPTION}. Change books folder")
    console.print(f"{SETTINGS_FOLDERS_OPTION}. Change feature folder names")
    console.print(f"{SETTINGS_READER_OPTION}. Change reader app")
    console.print(f"{SETTINGS_EXIT_OPTION}. Back")


def _update_guided_settings(store: ConfigStore, current: AyvuConfig, updated: AyvuConfig) -> AyvuConfig:
    if updated == current:
        console.print("Settings unchanged.")
        return current
    if _save_config(store, updated):
        console.print("[green]Settings saved.[/green]")
    return updated


def _settings_with_default_language(config: AyvuConfig) -> AyvuConfig:
    language = _prompt_target_language_code(config.default_target_language)
    if language == config.default_target_language:
        return config
    return replace(config, default_target_language=language)


def _settings_with_books_dir(config: AyvuConfig) -> AyvuConfig:
    books_dir = _prompt_path("Books folder", config.books_dir)
    if books_dir == config.books_dir:
        return config
    return replace(config, books_dir=books_dir)


def _settings_with_folder_names(config: AyvuConfig) -> AyvuConfig:
    try:
        folders = FolderNames.from_dict(
            {
                "original": _prompt_folder_name("Original folder name", config.folders.original),
                "translated": _prompt_folder_name("Translated folder name", config.folders.translated),
                "preview": _prompt_folder_name("Preview folder name", config.folders.preview),
                "reports": _prompt_folder_name("Reports folder name", config.folders.reports),
                "processing": _prompt_folder_name("Processing folder name", config.folders.processing),
            }
        )
    except ConfigError as exc:
        console.print(f"[red]Invalid folder name:[/red] {exc}")
        return config
    if folders == config.folders:
        return config
    return replace(config, folders=folders)


def _settings_with_reader_app(config: AyvuConfig) -> AyvuConfig:
    reader_app = _prompt_optional_text("Reader app command", config.reader_app)
    if reader_app == config.reader_app:
        return config
    return replace(config, reader_app=reader_app)


def _prompt_path(prompt: str, current: Path) -> Path:
    raw_path = typer.prompt(prompt, default=str(current)).strip()
    if not raw_path or raw_path == str(current):
        return current
    return Path(raw_path).expanduser()


def _prompt_folder_name(prompt: str, current: str) -> str:
    value = typer.prompt(prompt, default=current).strip()
    return value or current


def _prompt_optional_text(prompt: str, current: str | None) -> str | None:
    value = typer.prompt(prompt, default=current or "").strip()
    return value or None


def _choose_guided_target_language(default_target: str) -> str:
    console.print(f"[yellow]Default target language:[/yellow] {default_target}")
    console.print(f"{GUIDED_DEFAULT_LANGUAGE_OPTION}. Use default target language ({default_target})")
    console.print(f"{GUIDED_OTHER_LANGUAGE_OPTION}. Outro idioma")

    while True:
        choice = typer.prompt("Choose target language", default=GUIDED_DEFAULT_LANGUAGE_OPTION).strip()
        if choice == GUIDED_DEFAULT_LANGUAGE_OPTION:
            return default_target
        if choice == GUIDED_OTHER_LANGUAGE_OPTION:
            return _prompt_target_language_code(default_target)
        console.print("[red]Invalid option.[/red] Choose 1 or 2.")


def _prompt_target_language_code(default_target: str) -> str:
    available_languages = _load_languages_for_guided_selection()
    if available_languages:
        _print_guided_language_choices(available_languages)
    else:
        console.print("Enter a language code manually.")

    target = typer.prompt("Target language option or code", default=default_target).strip()
    selected = _language_code_from_guided_choice(target, available_languages)
    if selected:
        return selected
    return target or default_target


def _print_guided_language_choices(languages: tuple[TranslatorLanguage, ...]) -> None:
    table = Table(title="LibreTranslate languages")
    table.add_column("Option")
    table.add_column("Language")
    table.add_column("Code")
    table.add_column("State")

    for index, language in enumerate(languages, start=1):
        table.add_row(str(index), language.name, language.code, language.state)
    console.print(table)


def _language_code_from_guided_choice(choice: str, languages: tuple[TranslatorLanguage, ...]) -> str | None:
    if not choice.isdigit():
        return None

    index = int(choice)
    if 1 <= index <= len(languages):
        return languages[index - 1].code
    return None


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
    processing_dir: Path,
) -> tuple[ResumeStateStore, TranslationResumeState]:
    store = ResumeStateStore(processing_dir)
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
    if _has_glossary_summary(report):
        lines.extend(
            [
                f"- Glossary terms configured: {report.glossary_terms_configured}",
                f"- Glossary terms applied: {report.glossary_usage.total_applied}",
                f"- Required glossary terms missing: {len(report.glossary_usage.required_terms_missing)}",
                f"- Forbidden glossary terms found: {report.glossary_usage.total_forbidden_found}",
            ]
        )

    if report.errors:
        lines.extend(["", "## Errors"])
        lines.extend(f"- {_single_line(error)}" for error in report.errors)

    if report.glossary_usage.applied_terms:
        lines.extend(["", "## Glossary usage"])
        lines.extend(
            f"- {_single_line(term)}: {count}"
            for term, count in sorted(report.glossary_usage.applied_terms.items())
        )

    if report.glossary_usage.required_terms_missing or report.glossary_usage.forbidden_terms_found:
        lines.extend(["", "## Glossary warnings"])
        if report.glossary_usage.required_terms_missing:
            lines.append(
                f"- Required terms missing: {_format_terms(report.glossary_usage.required_terms_missing)}"
            )
        if report.glossary_usage.forbidden_terms_found:
            lines.append(
                f"- Forbidden terms found: {_format_counted_terms(report.glossary_usage.forbidden_terms_found)}"
            )

    if validation_warnings:
        lines.extend(["", "## Validation warnings"])
        lines.extend(f"- {_single_line(warning)}" for warning in validation_warnings)

    return "\n".join(lines) + "\n"


def _default_reports_dir() -> Path:
    return _reports_dir(_load_existing_config_or_default())


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


def _format_terms(terms: list[str]) -> str:
    return ", ".join(_single_line(term) for term in terms) if terms else "-"


def _format_counted_terms(counts: dict[str, int]) -> str:
    if not counts:
        return "-"
    return ", ".join(f"{_single_line(term)} ({count})" for term, count in sorted(counts.items()))


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


def _translated_books_dir(config: AyvuConfig) -> Path:
    if _uses_internal_storage_defaults(config):
        return default_translated_books_dir()
    return config.translated_dir


def _preview_books_dir(config: AyvuConfig) -> Path:
    if _uses_internal_storage_defaults(config):
        return default_preview_books_dir()
    return config.preview_dir


def _reports_dir(config: AyvuConfig) -> Path:
    if _uses_internal_storage_defaults(config):
        return Path.home() / "Documentos" / "Livros" / "Relatorios"
    return config.reports_dir


def _processing_dir(config: AyvuConfig) -> Path:
    if _uses_internal_storage_defaults(config):
        return default_processing_dir()
    return config.processing_dir


def _uses_internal_storage_defaults(config: AyvuConfig) -> bool:
    return config.books_dir == Path(DEFAULT_BOOKS_DIR) and config.folders == FolderNames()


if __name__ == "__main__":
    app()
