"""The one place a feature plugs into the app: one import and one list entry.

Importing a feature's routes also imports its models, which is how
Flask-Migrate sees every table.
"""
from flask import Flask

from app.account.routes import account_bp
from app.auth.routes import auth_bp
from app.health.routes import health_bp
from app.notes.routes import notes_bp

BLUEPRINTS = [account_bp, auth_bp, health_bp, notes_bp]


def register_features(app: Flask) -> None:
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
