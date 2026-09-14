from __future__ import annotations

from pathlib import Path


class DoclingParser:
    """Optional offline document converter; never runs in an API request."""

    def convert_to_markdown(self, source: str | Path) -> str:
        path = Path(source).resolve(strict=True)
        if not path.is_file():
            raise ValueError("document source must be a file")
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise RuntimeError(
                "Docling is not installed; install the 'documents' extra") from exc
        result = DocumentConverter().convert(str(path))
        markdown = result.document.export_to_markdown().strip()
        if not markdown:
            raise ValueError("Docling returned an empty document")
        return markdown
