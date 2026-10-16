"""
Turn uploaded bytes into plain text.

PDFs keep their page boundaries: pages are joined with PAGE_SEPARATOR and the
[start, end) span of every page inside the joined text is returned, so chunks
can be tagged with the page they came from and citations can jump to it.
"""
import io
import os

PAGE_SEPARATOR = "\n\n"

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".log": "text/plain; charset=utf-8",
}
SUPPORTED_EXTENSIONS = set(CONTENT_TYPES)


def file_extension(filename: str) -> str:
    return os.path.splitext(filename.lower())[1]


def guess_content_type(filename: str) -> str:
    return CONTENT_TYPES.get(file_extension(filename), "text/plain; charset=utf-8")


def _clean(text: str) -> str:
    # Postgres TEXT rejects NUL bytes, which pypdf occasionally emits.
    return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def extract_text(raw: bytes, filename: str) -> tuple[str, list[tuple[int, int]] | None]:
    """Return (text, page_spans). page_spans is None for non-paginated formats."""
    if file_extension(filename) == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        parts: list[str] = []
        spans: list[tuple[int, int]] = []
        cursor = 0
        for page in reader.pages:
            page_text = _clean(page.extract_text() or "").strip()
            if parts:
                cursor += len(PAGE_SEPARATOR)
            spans.append((cursor, cursor + len(page_text)))
            parts.append(page_text)
            cursor += len(page_text)
        return PAGE_SEPARATOR.join(parts), spans

    return _clean(raw.decode("utf-8-sig", errors="replace")), None
