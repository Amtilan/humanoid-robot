"""Basic `DocumentParserPort` implementations.

Every parser returns `(KnowledgeSource, raw_text)`.  Chunkers turn the
raw text into `KnowledgeChunk`s downstream — parsers do not do any
chunking or embedding here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from humanoid_robot.domain.knowledge import KnowledgeSource, KnowledgeSourceKind


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_id(uri: str, content_hash: str) -> str:
    return _hash(f"{uri}:{content_hash}".encode())


def _build_source(*, path: Path, text: str, kind: KnowledgeSourceKind) -> KnowledgeSource:
    encoded = text.encode("utf-8")
    content_hash = _hash(encoded)
    return KnowledgeSource(
        id=_source_id(path.as_uri(), content_hash),
        uri=path.as_uri(),
        kind=kind,
        title=path.stem,
        content_hash=content_hash,
    )


@dataclass(slots=True)
class TextParser:
    """Reads a UTF-8 text file verbatim."""

    def supported_kinds(self) -> tuple[str, ...]:
        return (KnowledgeSourceKind.TEXT.value,)

    async def parse(self, path: Path) -> tuple[KnowledgeSource, str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        return _build_source(path=path, text=text, kind=KnowledgeSourceKind.TEXT), text


@dataclass(slots=True)
class MarkdownParser:
    """Reads a Markdown file verbatim — chunker handles the structure."""

    def supported_kinds(self) -> tuple[str, ...]:
        return (KnowledgeSourceKind.MARKDOWN.value,)

    async def parse(self, path: Path) -> tuple[KnowledgeSource, str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        return (
            _build_source(path=path, text=text, kind=KnowledgeSourceKind.MARKDOWN),
            text,
        )


@dataclass(slots=True)
class HtmlParser:
    """Strips HTML to plain text via BeautifulSoup + a small tag denylist."""

    def supported_kinds(self) -> tuple[str, ...]:
        return (KnowledgeSourceKind.HTML.value,)

    async def parse(self, path: Path) -> tuple[KnowledgeSource, str]:
        from bs4 import BeautifulSoup  # runtime-cheap import

        raw = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "template"]):
            tag.decompose()
        text = "\n".join(
            line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()
        )
        return _build_source(path=path, text=text, kind=KnowledgeSourceKind.HTML), text


def build_text_parser(**_kwargs: object) -> TextParser:
    return TextParser()


def build_markdown_parser(**_kwargs: object) -> MarkdownParser:
    return MarkdownParser()


def build_html_parser(**_kwargs: object) -> HtmlParser:
    return HtmlParser()
