"""Write the JSON Schema of every request and response model to
frontend/src/api/schemas.json, which the frontend's `npm run api-types` turns
into TypeScript types. Run it, then that, after changing a schema:
tests/unit/test_export_schemas.py fails while the file is out of date.

Every app/**/schemas.py is read, so a new feature's models are picked up
without being listed anywhere.
"""
import importlib
import json
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode, models_json_schema

BACKEND = Path(__file__).resolve().parent
OUTPUT = BACKEND.parent / 'frontend' / 'src' / 'api' / 'schemas.json'


class WithoutFieldTitles(GenerateJsonSchema):
    """No title on each field ("Created At"), which the TypeScript generator
    would turn into a type alias of its own"""
    def field_title_should_be_set(self, schema: object) -> bool:
        return False


def schema_models() -> list[type[BaseModel]]:
    """Every model defined in a schemas module, by name"""
    found = []
    for path in sorted((BACKEND / 'app').rglob('schemas.py')):
        name = '.'.join(path.relative_to(BACKEND).with_suffix('').parts)
        module = importlib.import_module(name)
        found += [
            value for value in vars(module).values()
            if isinstance(value, type) and issubclass(value, BaseModel)
            and value.__module__ == name
        ]
    return sorted(found, key=lambda model: model.__name__)


def mode(model: type[BaseModel]) -> JsonSchemaMode:
    """A request is what the client sends, a response what it gets back"""
    return 'validation' if model.__name__.endswith(('Request', 'Query')) else 'serialization'


def export() -> str:
    _, schema = models_json_schema(
        [(model, mode(model)) for model in schema_models()],
        schema_generator=WithoutFieldTitles)
    return json.dumps(schema, indent=2, sort_keys=True) + '\n'


if __name__ == '__main__':
    OUTPUT.write_text(export(), encoding='utf-8')
