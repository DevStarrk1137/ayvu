from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_SCOPE = PROJECT_ROOT / "docs" / "product-scope.md"
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_product_scope_local_markdown_links_resolve_inside_repository() -> None:
    """Keep the published taxonomy navigable in a fresh clone."""
    assert PRODUCT_SCOPE.is_file()

    for match in MARKDOWN_LINK.finditer(PRODUCT_SCOPE.read_text(encoding="utf-8")):
        target = match.group(1).strip()
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue

        relative_path = target.split("#", maxsplit=1)[0]
        resolved = (PRODUCT_SCOPE.parent / relative_path).resolve()
        assert resolved.is_relative_to(PROJECT_ROOT.resolve())
        assert resolved.exists(), f"broken local link in {PRODUCT_SCOPE.name}: {target}"
