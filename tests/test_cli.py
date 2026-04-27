from pathlib import Path

from ayvu.cli import _resolve_output_path


def test_resolve_output_path_keeps_explicit_output():
    output = Path("traduzidos/livro-final.epub")

    assert _resolve_output_path(Path("livro.epub"), output, "pt") == output


def test_resolve_output_path_uses_target_suffix_next_to_input():
    assert _resolve_output_path(Path("books/livro.epub"), None, "pt-BR") == Path("books/livro-pt-BR.epub")

