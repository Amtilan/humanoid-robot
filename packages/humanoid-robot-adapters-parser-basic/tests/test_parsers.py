"""Basic parser tests."""

from __future__ import annotations

from pathlib import Path

from humanoid_robot.adapters.parser_basic import (
    HtmlParser,
    MarkdownParser,
    TextParser,
)
from humanoid_robot.domain.knowledge import KnowledgeSourceKind


class TestTextParser:
    async def test_reads_text_verbatim(self, tmp_path: Path) -> None:
        f = tmp_path / "note.txt"
        f.write_text("Hello, robot.", encoding="utf-8")
        source, text = await TextParser().parse(f)
        assert text == "Hello, robot."
        assert source.kind == KnowledgeSourceKind.TEXT
        assert source.title == "note"
        assert source.uri == f.as_uri()

    async def test_deterministic_source_id(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f1.write_text("Same content", encoding="utf-8")
        s1, _ = await TextParser().parse(f1)
        s2, _ = await TextParser().parse(f1)
        assert s1.id == s2.id

    async def test_source_id_changes_when_content_changes(self, tmp_path: Path) -> None:
        f = tmp_path / "n.txt"
        f.write_text("A", encoding="utf-8")
        s1, _ = await TextParser().parse(f)
        f.write_text("B", encoding="utf-8")
        s2, _ = await TextParser().parse(f)
        assert s1.id != s2.id
        assert s1.content_hash != s2.content_hash


class TestMarkdownParser:
    async def test_reads_markdown_verbatim(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("# Title\n\nBody.\n", encoding="utf-8")
        source, text = await MarkdownParser().parse(f)
        assert text.startswith("# Title")
        assert source.kind == KnowledgeSourceKind.MARKDOWN


class TestHtmlParser:
    async def test_strips_tags_and_scripts(self, tmp_path: Path) -> None:
        html = (
            "<html><head><title>t</title>"
            "<script>alert(1)</script>"
            "<style>body {}</style></head>"
            "<body><h1>Header</h1>"
            "<p>Paragraph.</p></body></html>"
        )
        f = tmp_path / "page.html"
        f.write_text(html, encoding="utf-8")
        source, text = await HtmlParser().parse(f)
        assert "Header" in text
        assert "Paragraph." in text
        assert "alert" not in text
        assert "body {}" not in text
        assert source.kind == KnowledgeSourceKind.HTML
