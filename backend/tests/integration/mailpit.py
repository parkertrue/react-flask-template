"""Mailpit, where the email the worker sends in the test stack arrives,
read through its API (MAILPIT_API_URL)"""
import json
import os
from urllib.parse import quote
# Mailpit's API, the test stack's mail server
from urllib.request import Request, urlopen  # noqa: TID251


def mailpit(path, method='GET'):
    request = Request(os.environ['MAILPIT_API_URL'] + path, method=method)
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read()) if method == 'GET' else None


def inbox(address):
    """The messages Mailpit received for address"""
    summaries = mailpit(f'/search?query={quote(f"to:{address}")}')['messages']
    return [mailpit(f"/message/{summary['ID']}") for summary in summaries]
