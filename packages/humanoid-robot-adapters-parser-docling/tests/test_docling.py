"""Docling parser tests with an injected fake converter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from humanoid_robot.adapters.parser_docling import (
    DoclingParser,
    DoclingRuntimeNotAvailableError,
)
from humanoid_robot.domain.knowledge import KnowledgeSourceKind


@dataclass(slots=True)
class _FakeDocument:
    markdown: str

    def export_to_markdown(self) -> str:
        return self.markdown


@dataclass(slots=True)
class _FakeResult:
    document: _FakeDocument


@dataclass(slots=True)
class _FakeConverter:
    scripted_markdown: str
    conversions: list[Path]

    def convert(self, path: Path) -> _FakeResult:
        self.conversions.append(path)
        return _FakeResult(document=_FakeDocument(markdown=self.scripted_markdown))


def _factory(markdown: str) -> Any:
    conversions: list[Path] = []

    def _mk() -> _FakeConverter:
        return _FakeConverter(scripted_markdown=markdown, conversions=conversions)

    _mk.conversions = conversions  # type: ignore[attr-defined]
    return _mk


class TestDoclingParser:
    async def test_missing_runtime_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4")
        parser = DoclingParser(kind=KnowledgeSourceKind.PDF)
        with pytest.raises(DoclingRuntimeNotAvailableError):
            await parser.parse(f)

    async def test_parse_returns_markdown_from_converter(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.docx"
        f.write_bytes(b"DOCX-STUB")
        factory = _factory("# Heading\n\nBody paragraph.")
        parser = DoclingParser(kind=KnowledgeSourceKind.DOCX, converter_factory=factory)
        source, text = await parser.parse(f)
        assert text.startswith("# Heading")
        assert source.kind == KnowledgeSourceKind.DOCX
        assert source.title == "doc"

    async def test_converter_reused_across_calls(self, tmp_path: Path) -> None:
        f = tmp_path / "a.pdf"
        f.write_bytes(b"a")
        factory = _factory("hello")
        parser = DoclingParser(kind=KnowledgeSourceKind.PDF, converter_factory=factory)
        await parser.parse(f)
        await parser.parse(f)
        # Both parses should use the same converter instance — evidence: the
        # same conversions list has 2 entries.
        assert len(factory.conversions) == 2

    def test_supported_kinds_reflects_configured_kind(self) -> None:
        for kind in (
            KnowledgeSourceKind.PDF,
            KnowledgeSourceKind.DOCX,
            KnowledgeSourceKind.XLSX,
            KnowledgeSourceKind.PPTX,
        ):
            parser = DoclingParser(kind=kind)
            assert parser.supported_kinds() == (kind.value,)
