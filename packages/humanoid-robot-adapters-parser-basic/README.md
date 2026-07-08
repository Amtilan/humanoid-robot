# humanoid-robot-adapters-parser-basic

Simple `DocumentParserPort` implementations that ship in the runtime by
default because they are cheap and have no ML dependencies:

- `text` — TXT files (UTF-8), passthrough.
- `markdown` — Markdown files, kept verbatim (chunker splits on headings).
- `html` — HTML files, stripped to plain text via BeautifulSoup.

Structured PDF/DOCX/XLSX/PPTX parsing lives in a separate package
(`humanoid-robot-adapters-parser-docling`) which pulls the Docling runtime.
Split so operators can install the cheap stack without paying for Docling
disk space when they only ingest plain text.
