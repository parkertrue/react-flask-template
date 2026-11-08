"""A user's data export holds everything the app keeps on them.

GET /api/account/export writes each feature's rows that the feature
registered (app/utils/exports.py). A table that references users.id holds
a user's data, so it must be in an export, or the export leaves it out.
"""
from app import db
from app.utils.exports import registered_exports


def test_every_table_a_user_owns_is_exported(app):
    """Requests app: building it imports every feature's models. With no
    feature that keeps a user's rows, there is nothing to export."""
    with app.app_context():
        exported = {export.model.__table__.name for export in registered_exports().values()}
    owned = {table.name for table in db.metadata.tables.values()
             if any(fk.column.table.name == 'users' for fk in table.foreign_keys)}

    assert owned - exported == set()
