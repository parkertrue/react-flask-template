"""export_schemas.py, whose output the frontend's API types are generated from."""
import pytest
from pydantic import BaseModel

import export_schemas


def test_the_frontend_has_the_current_schemas():
    # read_text undoes a Windows checkout's CRLF
    committed = export_schemas.OUTPUT.read_text(encoding='utf-8')

    assert committed == export_schemas.export(), (
        'frontend/src/api/schemas.json is out of date: run `python export_schemas.py` '
        'from backend/, then `npm run api-types` from frontend/')


class PingRequest(BaseModel):
    pass


class PingQuery(BaseModel):
    pass


class PingResponse(BaseModel):
    pass


@pytest.mark.parametrize(('model', 'expected'), [
    (PingRequest, 'validation'),
    (PingQuery, 'validation'),
    (PingResponse, 'serialization'),
])
def test_requests_are_what_the_client_sends_and_responses_what_it_gets(model, expected):
    assert export_schemas.mode(model) == expected
