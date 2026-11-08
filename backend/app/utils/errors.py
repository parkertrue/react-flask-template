from flask import Response, jsonify
from pydantic import BaseModel

# What every error helper returns: the JSON body and its status
ErrorResponse = tuple[Response, int]


# Every outage answers 503 with these words, whichever service is down:
# the user can only wait.
SERVICE_UNAVAILABLE_MESSAGE = 'The service is temporarily unavailable, please try again shortly'


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorBody(BaseModel):
    """Every error response's body, the backend's and nginx's alike"""
    error: ErrorDetail


# Keyword-only, so the error-code sync test (frontend fixtures.test.ts) can
# find every code by its `code='...'`
def error_response(*, code: str, message: str, status: int = 400) -> ErrorResponse:
    body = ErrorBody(error=ErrorDetail(code=code, message=message))
    return jsonify(body.model_dump()), status


# A service the request needs is down (MySQL, Redis) or too busy to answer
def service_unavailable(message: str = SERVICE_UNAVAILABLE_MESSAGE) -> ErrorResponse:
    return error_response(code='SERVICE_UNAVAILABLE', message=message, status=503)


# A create refused because the user already stores as many rows of that kind
# as a feature allows. Shared, so every feature answers a full quota alike.
def quota_exceeded(message: str) -> ErrorResponse:
    return error_response(code='QUOTA_EXCEEDED', message=message, status=409)
