"""Whether a password has appeared in a data breach (NIST SP 800-63B).

Checked against Have I Been Pwned's Pwned Passwords, through its range API:
only the first 5 hex characters of the password's SHA-1 leave the server,
and the API answers with every breached hash that starts with them (padded
with decoys, so the answer's size tells nothing), which are compared here.
The password, and its full hash, never leave.

Fails open: an outage or a slow answer lets the password through, logged,
rather than stop sign-up (DECISIONS.md). Production checks by default;
elsewhere only when PWNED_PASSWORDS_URL is set (config.py).
"""
import hashlib
import urllib.request

from flask import current_app

# Each sign-up waits on it, so it gives up well before a user would
TIMEOUT_SECONDS = 2


def is_breached(password: str) -> bool:
    """Whether the password is in Pwned Passwords; False when the check is
    off or could not be made"""
    url: str | None = current_app.config['PWNED_PASSWORDS_URL']
    if not url:
        return False
    # A lookup key, not a protection: the API is keyed on SHA-1
    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    request = urllib.request.Request(
        url + prefix, headers={'Add-Padding': 'true', 'User-Agent': 'react-flask-template'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode('ascii')
    except (OSError, ValueError) as e:
        # Unreachable, timed out, refused (an HTTPError is an OSError) or
        # garbled. Only the kind: nothing of the password is in it anyway.
        current_app.logger.warning(
            'breach_check_failed', extra={'fields': {'reason': type(e).__name__}})
        return False
    for line in body.splitlines():
        candidate, _, count = line.partition(':')
        # Padding's decoys have a count of 0
        if candidate == suffix and count.strip() not in ('', '0'):
            return True
    return False
