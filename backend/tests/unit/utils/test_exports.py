"""The export registry, on models of its own: the app's are a feature's"""
import pytest
from flask import Blueprint, Flask
from pydantic import BaseModel
from sqlalchemy import ForeignKey, insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils.exports import export_user_data, register_export


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)


class Owned(Base):
    __tablename__ = 'owned'
    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[int] = mapped_column(ForeignKey('users.id'))
    label: Mapped[str]


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


class LabelledRow(Row):
    label: str


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


@pytest.fixture
def owned_table(app, db, monkeypatch):
    """Owned's table in the unit database (whose users table it references),
    as the one registered export"""
    blueprint = Blueprint('owned', __name__)
    register_export(blueprint, 'owned', Owned, LabelledRow)
    registry = Flask(__name__)
    registry.register_blueprint(blueprint)
    monkeypatch.setitem(app.extensions, 'data_exports', registry.extensions['data_exports'])
    Owned.__table__.create(db.engine)
    yield
    db.session.rollback()
    Owned.__table__.drop(db.engine)


@pytest.mark.usefixtures('owned_table')
def test_exports_the_users_rows_of_each_registered_table_oldest_first(db, sample_user, second_user):
    db.session.execute(insert(Owned), [
        {'id': 2, 'account': sample_user.id, 'label': 'newer'},
        {'id': 1, 'account': sample_user.id, 'label': 'older'},
        {'id': 3, 'account': second_user.id, 'label': 'not theirs'},
    ])

    assert export_user_data(sample_user.id) == {
        'owned': [{'id': 1, 'label': 'older'}, {'id': 2, 'label': 'newer'}]}


def test_exports_nothing_when_no_feature_registered(app, db, sample_user, monkeypatch):
    monkeypatch.delitem(app.extensions, 'data_exports', raising=False)

    assert export_user_data(sample_user.id) == {}
