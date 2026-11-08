"""What a user's data export holds beyond the account: every feature's rows.

GET /api/account/export lives in account/, which may not import a feature,
so each feature registers its own table here, from its blueprint. Removing a
feature removes its registration with it. tests/unit/test_exports.py fails on
a table that references users.id and is in no export.
"""
from dataclasses import dataclass

from flask import Blueprint, current_app
from flask.blueprints import BlueprintSetupState
from pydantic import BaseModel, JsonValue
from sqlalchemy import Column, select

from app import Base, db


@dataclass(frozen=True)
class DataExport:
    model: type[Base]
    # How each row is written: the feature's response schema, so the export
    # shows what the user sees in the app
    schema: type[BaseModel]
    # The model's column referencing users.id: whose rows these are
    owner: Column[int]


def _owner_column(model: type[Base]) -> Column[int]:
    owners = [fk.parent for fk in model.__table__.foreign_keys
              if fk.column.table.name == 'users']
    if len(owners) != 1:
        raise ValueError(f'{model.__name__} must reference users.id exactly once to be exported')
    return owners[0]


def register_export(
        blueprint: Blueprint, name: str, model: type[Base], schema: type[BaseModel]) -> None:
    """Export the signed-in user's rows of model under name, each through schema"""
    export = DataExport(model, schema, _owner_column(model))

    def record(state: BlueprintSetupState) -> None:
        exports: dict[str, DataExport] = state.app.extensions.setdefault('data_exports', {})
        if name in exports:
            raise ValueError(f'Two features export under the name {name!r}')
        exports[name] = export

    blueprint.record_once(record)


def registered_exports() -> dict[str, DataExport]:
    exports: dict[str, DataExport] = current_app.extensions.get('data_exports', {})
    return exports


def export_user_data(user_id: int) -> dict[str, list[dict[str, JsonValue]]]:
    """Every registered feature's rows owned by user_id, oldest first. One
    query per feature, unpaginated: each feature caps a user's rows (a
    quota), which bounds the export too."""
    data: dict[str, list[dict[str, JsonValue]]] = {}
    for name, export in sorted(registered_exports().items()):
        rows = db.session.execute(
            select(export.model).where(export.owner == user_id)
            .order_by(*export.model.__table__.primary_key)).scalars()
        data[name] = [export.schema.model_validate(row).model_dump(mode='json') for row in rows]
    return data
