"""The export registry, on models of its own: the app's are a feature's"""
import pytest
from flask import Blueprint, Flask
from pydantic import BaseModel
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils.exports import register_export


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)


class Owned(Base):
    __tablename__ = 'owned'
    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[int] = mapped_column(ForeignKey('users.id'))


class Unowned(Base):
    __tablename__ = 'unowned'
    id: Mapped[int] = mapped_column(primary_key=True)


class Shared(Base):
    __tablename__ = 'shared'
    id: Mapped[int] = mapped_column(primary_key=True)
    sender: Mapped[int] = mapped_column(ForeignKey('users.id'))
    recipient: Mapped[int] = mapped_column(ForeignKey('users.id'))


class Row(BaseModel):
    id: int


def test_finds_the_column_naming_the_owner():
    blueprint = Blueprint('owned', __name__)
    register_export(blueprint, 'owned', Owned, Row)
    app = Flask(__name__)

    app.register_blueprint(blueprint)

    assert app.extensions['data_exports']['owned'].owner is Owned.__table__.c.account


@pytest.mark.parametrize('model', [Unowned, Shared])
def test_refuses_a_model_without_exactly_one_owner(model):
    """Whose rows a shared one holds is the feature's call, not a guess"""
    with pytest.raises(ValueError, match='must reference users.id exactly once'):
        register_export(Blueprint('x', __name__), 'x', model, Row)


def test_refuses_two_exports_under_one_name():
    first, second = Blueprint('first', __name__), Blueprint('second', __name__)
    register_export(first, 'rows', Owned, Row)
    register_export(second, 'rows', Owned, Row)
    app = Flask(__name__)
    app.register_blueprint(first)

    with pytest.raises(ValueError, match="Two features export under the name 'rows'"):
        app.register_blueprint(second)
