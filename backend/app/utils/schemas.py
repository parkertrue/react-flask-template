from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

# A timestamp in a response schema. MySQL's DATETIME holds no zone, so the
# database hands back naive values; every timestamp is UTC (config pins the
# connection to it). Say so in the output, or browsers read it as their
# local time.
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(lambda dt: dt.replace(tzinfo=timezone.utc).isoformat(), return_type=str),
]


class MessageResponse(BaseModel):
    """A reply that only says what happened: registered, logged out, ..."""
    message: str
