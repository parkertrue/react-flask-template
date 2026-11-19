"""The name a session's device is listed under, from its User-Agent.

Only the name is kept, never the User-Agent itself: enough for a user to
recognise their own devices on the account page, and no more personal data
than that needs (docs/personal-data.md).
"""
import ua_parser

# A User-Agent longer than any real one is cut short before it is parsed:
# the parser runs regular expressions over it, on a request's time
USER_AGENT_PARSE_LIMIT = 512

# Families named as their makers name them today
_RENAMED = {'Mac OS X': 'macOS'}


def _family(family: str | None) -> str | None:
    if family is None or family == 'Other':
        return None
    return _RENAMED.get(family, family)


def device_name(user_agent: str | None) -> str:
    """"Firefox on Windows", or as much of it as the User-Agent tells"""
    parsed = ua_parser.parse((user_agent or '')[:USER_AGENT_PARSE_LIMIT])
    browser = _family(parsed.user_agent.family if parsed.user_agent else None)
    system = _family(parsed.os.family if parsed.os else None)
    if browser and system:
        return f'{browser} on {system}'
    if browser or system:
        return browser or f'A browser on {system}'
    return 'Unknown device'
