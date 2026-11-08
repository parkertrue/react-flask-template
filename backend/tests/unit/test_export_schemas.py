"""export_schemas.py, whose output the frontend's API types are generated from."""
import export_schemas


def test_the_frontend_has_the_current_schemas():
    # read_text undoes a Windows checkout's CRLF
    committed = export_schemas.OUTPUT.read_text(encoding='utf-8')

    assert committed == export_schemas.export(), (
        'frontend/src/api/schemas.json is out of date: run `python export_schemas.py` '
        'from backend/, then `npm run api-types` from frontend/')


def test_requests_are_what_the_client_sends_and_responses_what_it_gets():
    models = {model.__name__: export_schemas.mode(model) for model in export_schemas.schema_models()}

    assert models['LoginRequest'] == 'validation'
    assert models['NotesListQuery'] == 'validation'
    assert models['NoteResponse'] == 'serialization'
