"""Docling-backed `DocumentParserPort` implementations.

Docling emits document-structure-aware Markdown for every supported format,
which we pass through verbatim to the chunker. The heavy `DocumentConverter`
is created once and reused across `parse()` calls to amortise the model
load; a per-instance `_converter_factory` hook lets tests inject a fake.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from humanoid_robot.domain.knowledge import KnowledgeSource, KnowledgeSourceKind


class DoclingRuntimeNotAvailableError(RuntimeError):
    """Raised when Docling is not installed at runtime."""

    def __init__(self) -> None:
        super().__init__(
            "docling is not installed. Install this adapter with its runtime "
            "extra: uv add 'humanoid-robot-adapters-parser-docling[runtime]'"
        )


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_id(uri: str, content_hash: str) -> str:
    return _hash(f"{uri}:{content_hash}".encode())


@dataclass(slots=True)
class DoclingParser:
    """Wraps `docling.document_converter.DocumentConverter` for one kind."""

    kind: KnowledgeSourceKind
    _converter_factory: Any = None  # injectable in tests
    _converter: Any = field(default=None, init=False)

    def __init__(
        self,
        kind: KnowledgeSourceKind,
        *,
        converter_factory: Any = None,
    ) -> None:
        self.kind = kind
        self._converter_factory = converter_factory
        self._converter = None

    def supported_kinds(self) -> tuple[str, ...]:
        return (self.kind.value,)

    async def parse(self, path: Path) -> tuple[KnowledgeSource, str]:
        converter = self._ensure_converter()
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, lambda: _extract_markdown(converter, path))
        content_hash = _hash(text.encode("utf-8"))
        source = KnowledgeSource(
            id=_source_id(path.as_uri(), content_hash),
            uri=path.as_uri(),
            kind=self.kind,
            title=path.stem,
            content_hash=content_hash,
        )
        return source, text

    def _ensure_converter(self) -> Any:
        if self._converter is not None:
            return self._converter
        if self._converter_factory is not None:
            self._converter = self._converter_factory()
            return self._converter
        try:
            document_converter = importlib.import_module("docling.document_converter")
        except ImportError as exc:
            raise DoclingRuntimeNotAvailableError from exc
        self._converter = document_converter.DocumentConverter()
        return self._converter


def _extract_markdown(converter: Any, path: Path) -> str:
    result = converter.convert(path)
    document = getattr(result, "document", None)
    if document is None:
        return ""
    export_markdown = getattr(document, "export_to_markdown", None)
    if callable(export_markdown):
        return str(export_markdown())
    export_text = getattr(document, "export_to_text", None)
    if callable(export_text):
        return str(export_text())
    return str(document)


def _mk_factory(kind: KnowledgeSourceKind) -> Any:
    def _factory(**_kwargs: object) -> DoclingParser:
        return DoclingParser(kind=kind)

    return _factory


build_pdf_parser = _mk_factory(KnowledgeSourceKind.PDF)
build_docx_parser = _mk_factory(KnowledgeSourceKind.DOCX)
build_xlsx_parser = _mk_factory(KnowledgeSourceKind.XLSX)
build_pptx_parser = _mk_factory(KnowledgeSourceKind.PPTX)
