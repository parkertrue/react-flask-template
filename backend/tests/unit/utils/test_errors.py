import json

import pytest

from app.utils.errors import (
    SERVICE_UNAVAILABLE_MESSAGE, error_response, quota_exceeded, service_unavailable)


# jsonify needs an app context, which the app fixture holds open
@pytest.mark.usefixtures('app')
class TestErrorResponse:
    """Test suite for error_response utility function."""

    def test_error_response_basic(self):
        """error_response should return tuple with dict and status."""
        response, status = error_response(
            code='TEST_ERROR',
            message='Test error message',
            status=400
        )

        assert status == 400
        data = json.loads(response.data)
        assert data['error']['code'] == 'TEST_ERROR'
        assert data['error']['message'] == 'Test error message'

    def test_error_response_structure(self):
        """error_response should have consistent structure."""
        response, status = error_response(
            code='VALIDATION_ERROR',
            message='Validation failed',
            status=422
        )

        data = json.loads(response.data)
        assert 'code' in data['error']
        assert 'message' in data['error']
        assert isinstance(data['error']['code'], str)
        assert isinstance(data['error']['message'], str)

    @pytest.mark.parametrize(('status_code', 'message'), [
        (400, 'Bad Request'),
        (401, 'Unauthorized'),
        (403, 'Forbidden'),
        (404, 'Not Found'),
        (409, 'Conflict'),
        (422, 'Unprocessable Entity'),
        (500, 'Internal Server Error'),
    ])
    def test_error_response_different_status_codes(self, status_code, message):
        """error_response should work with various status codes."""
        response, status = error_response(
            code=f'ERROR_{status_code}',
            message=message,
            status=status_code
        )

        assert status == status_code
        data = json.loads(response.data)
        assert data['error']['message'] == message

    def test_error_response_takes_keywords_only(self):
        with pytest.raises(TypeError):
            error_response('TEST_ERROR', 'Test error message')

    # Tested here too: a new app deletes the example feature that uses it
    def test_quota_exceeded_is_a_409_with_its_message(self):
        response, status = quota_exceeded('You can keep at most 3 things.')

        assert status == 409
        assert response.get_json()['error'] == {
            'code': 'QUOTA_EXCEEDED', 'message': 'You can keep at most 3 things.'}

    @pytest.mark.parametrize(('args', 'message'), [
        ((), SERVICE_UNAVAILABLE_MESSAGE),
        (('The server is busy',), 'The server is busy'),
    ])
    def test_service_unavailable_is_a_503(self, args, message):
        response, status = service_unavailable(*args)

        assert status == 503
        assert response.get_json()['error'] == {'code': 'SERVICE_UNAVAILABLE', 'message': message}
