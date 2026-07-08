# humanoid-robot-adapters-parser-docling

Structured `DocumentParserPort` implementations for PDF, DOCX, XLSX, PPTX on
top of [Docling](https://github.com/DS4SD/docling). Docling produces layout-
aware Markdown-like output (tables, headings, lists) which pairs well with
the paragraph-first `token` chunker.

Kept in a separate distribution from `humanoid-robot-adapters-parser-basic`
because Docling pulls a large runtime footprint (transformers, torch,
tesseract wrappers). Robots that only ingest plain text should install the
basic package and skip this one.

## Installation

```bash
uv add "humanoid-robot-adapters-parser-docling[runtime]"
```

The `runtime` extra pulls Docling; the adapter package itself imports fine
without the extra, so tests and packaging work on developer laptops.
