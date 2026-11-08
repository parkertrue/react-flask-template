"""A user's data export holds everything the app keeps on them.

GET /api/account/export writes each feature's rows that the feature
registered (app/utils/exports.py). A table that references users.id holds
a user's data, so it must be in an export, or the export leaves it out.
"""
from app import db


def test_every_table_a_user_owns_is_exported(app):
    """Requests app: building it imports every feature's models"""
    exported = {export.model.__table__.name for export in app.extensions['data_exports'].values()}
    owned = {table.name for table in db.metadata.tables.values()
             if any(fk.column.table.name == 'users' for fk in table.foreign_keys)}

    assert owned - exported == set()
