"""
Offset-preserving text splitter.

Every chunk is an exact slice `content[char_start:char_end]` of the document
text, which is what lets the UI highlight the cited passage. Chunks prefer to
end on the strongest nearby boundary (paragraph > line > sentence > clause >
word) and never cross a PDF page, so each one maps to a single page.
"""
import re
from dataclasses import dataclass

SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]
_WHITESPACE = re.compile(r"\s")


@dataclass
class Piece:
    content: str
    char_start: int
    char_end: int
    page: int | None


def _skip_ws(text: str, pos: int, hi: int) -> int:
    while pos < hi and text[pos].isspace():
        pos += 1
    return pos


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    start = _skip_ws(text, start, end)
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split_spans(text: str, chunk_size: int, chunk_overlap: int, lo: int = 0, hi: int | None = None) -> list[tuple[int, int]]:
    """Split text[lo:hi] into overlapping (start, end) spans of at most ~chunk_size chars."""
    hi = len(text) if hi is None else hi
    chunk_overlap = min(chunk_overlap, chunk_size // 2)
    spans: list[tuple[int, int]] = []

    start = _skip_ws(text, lo, hi)
    while start < hi:
        end = min(start + chunk_size, hi)
        if end < hi:
            # Look for the best boundary in the back half of the window
            floor = start + chunk_size // 2
            for sep in SEPARATORS:
                idx = text.rfind(sep, floor, end)
                if idx != -1:
                    end = idx + len(sep)
                    break

        s, e = _trim(text, start, end)
        if e > s:
            spans.append((s, e))
        if end >= hi:
            break

        nxt = max(end - chunk_overlap, start + 1)
        if nxt < end:
            # Don't start the overlap mid-word
            ws = _WHITESPACE.search(text, nxt, end)
            if ws:
                nxt = ws.end()
        start = _skip_ws(text, nxt, hi)

    # Fold a tiny trailing chunk into its predecessor
    if len(spans) > 1 and spans[-1][1] - spans[-1][0] < chunk_size // 4:
        last = spans.pop()
        spans[-1] = (spans[-1][0], last[1])

    return spans


def chunk_document(
    content: str,
    pages: list[tuple[int, int]] | None,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Piece]:
    ranges = (
        [(i + 1, lo, hi) for i, (lo, hi) in enumerate(pages)]
        if pages
        else [(None, 0, len(content))]
    )
    return [
        Piece(content[s:e], s, e, page)
        for page, lo, hi in ranges
        for s, e in split_spans(content, chunk_size, chunk_overlap, lo, hi)
    ]
