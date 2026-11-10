"""Script text from a PDF."""

from io import BytesIO


def extract_text(raw_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(raw_bytes))
    return "\n\n".join(t for t in ((p.extract_text() or "").strip() for p in reader.pages) if t).strip()
