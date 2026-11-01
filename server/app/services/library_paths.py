"""Match indexed files within a library without matching sibling directories."""

from sqlalchemy import ColumnElement

from app.models import MediaFile


def library_file_filter(library_path: str) -> ColumnElement[bool]:
    prefix = library_path.rstrip("/") + "/"
    return MediaFile.file_path.startswith(prefix, autoescape=True)
