from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.notes.models import NOTE_MAX_LENGTH
from app.utils.ids import ID_MAX
from app.utils.schemas import UtcDatetime
from app.utils.text import UNSUPPORTED_CHARACTERS_MESSAGE, is_plain_text


class NoteCreateRequest(BaseModel):
    # Stored as the user typed it, markup included. Output safety belongs to
    # the render layer: React escapes text, so "<b>" shows as "<b>". Never
    # inject it as HTML (dangerouslySetInnerHTML, innerHTML) without
    # sanitizing at that point.
    content: str = Field(min_length=1, max_length=NOTE_MAX_LENGTH)

    # Trimmed before the length checks, so whitespace-only notes are rejected
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('content')
    @classmethod
    def check_characters(cls, v: str) -> str:
        if not is_plain_text(v):
            raise ValueError(f'Note {UNSUPPORTED_CHARACTERS_MESSAGE}')
        return v


class NoteUpdateRequest(NoteCreateRequest):
    """PUT /api/notes/<id>: the note's new content, under the same rules"""


class NotesListQuery(BaseModel):
    """GET /api/notes query string: ?before=<next_cursor>&limit=<n>"""
    before: int | None = Field(default=None, ge=1, le=ID_MAX)
    limit: int = Field(default=20, ge=1, le=100)

    # A misspelled key (?befor=) is a 422, not a silent first page
    model_config = ConfigDict(extra='forbid')


class NoteResponse(BaseModel):
    id: int
    content: str
    created_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)
