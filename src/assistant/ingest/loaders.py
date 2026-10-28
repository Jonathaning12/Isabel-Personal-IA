"""Turn uploaded files (bytes) into plain text. Supported: Markdown, plain text, PDF."""

from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader

MARKDOWN_EXTENSIONS = {".md", ".markdown"}
SUPPORTED_EXTENSIONS = MARKDOWN_EXTENSIONS | {".txt", ".pdf"}


class UnsupportedFileError(ValueError):
    """The file type is not supported for ingestion."""


def extension(filename: str) -> str:
    return PurePath(filename).suffix.lower()


def is_markdown(filename: str) -> bool:
    return extension(filename) in MARKDOWN_EXTENSIONS


def load_text(filename: str, data: bytes) -> str:
    """Extract text from a file's bytes based on its extension."""
    ext = extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"Unsupported file type: {ext or '(none)'}")
    if ext == ".pdf":
        reader = PdfReader(BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return data.decode("utf-8", errors="replace")
