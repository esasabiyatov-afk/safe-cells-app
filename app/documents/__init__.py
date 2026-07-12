"""Safe DOCX template inspection and rendering."""

from app.documents.renderer import (
    DocumentPublishError,
    DocumentTemplateError,
    render_docx,
)

__all__ = ["DocumentPublishError", "DocumentTemplateError", "render_docx"]
