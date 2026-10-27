"""Every timestamp a schema declares is a UtcDatetime.

The database hands back naive values, which a plain datetime serializes
without a zone, and browsers then read as their own local time.
"""
import importlib
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional, get_args, get_origin

import pytest
from pydantic import BaseModel

from app.utils.schemas import UtcDatetime

APP = Path(__file__).resolve().parents[3] / 'app'
UTC = get_args(UtcDatetime)[1]


def _has_bare_datetime(annotation, metadata=()):
    if annotation is datetime:
        return UTC not in metadata
    if get_origin(annotation) is Annotated:
        base, *extra = get_args(annotation)
        return _has_bare_datetime(base, extra)
    return any(_has_bare_datetime(arg) for arg in get_args(annotation))


def _bare_datetimes(models):
    return [f'{model.__name__}.{name}' for model in models
            for name, field in model.model_fields.items()
            if _has_bare_datetime(field.annotation, field.metadata)]


def _schemas():
    """Every model each feature's schemas.py defines"""
    for path in sorted(APP.glob('*/schemas.py')):
        module = importlib.import_module(f'app.{path.parent.name}.schemas')
        yield from (value for value in vars(module).values()
                    if isinstance(value, type) and issubclass(value, BaseModel)
                    and value.__module__ == module.__name__)


def test_finds_the_schemas():
    names = {model.__name__ for model in _schemas()}
    # Only shared ones are named: the examples can be deleted (README,
    # Starting a New App)
    assert {'AccountResponse', 'LoginRequest', 'RegisterRequest'} <= names


def test_every_timestamp_is_a_utc_datetime():
    assert _bare_datetimes(_schemas()) == []


def test_utc_datetime_states_the_zone():
    class Stamped(BaseModel):
        at: UtcDatetime

    # Naive, as MySQL's DATETIME comes back
    naive = datetime.fromisoformat('2026-01-02T03:04:05')

    assert Stamped(at=naive).model_dump_json() == '{"at":"2026-01-02T03:04:05+00:00"}'


class TestTheCheckItself:
    class Bare(BaseModel):
        created_at: datetime
        updated_at: Optional[datetime] = None
        history: list[datetime] = []

    class Zoned(BaseModel):
        created_at: UtcDatetime
        updated_at: Optional[UtcDatetime] = None
        history: list[UtcDatetime] = []
        title: str = ''

    @pytest.mark.parametrize(('model', 'found'), [
        (Bare, ['Bare.created_at', 'Bare.updated_at', 'Bare.history']),
        (Zoned, []),
    ])
    def test_finds_a_bare_datetime_however_it_is_nested(self, model, found):
        assert _bare_datetimes([model]) == found
