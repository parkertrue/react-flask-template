"""The names sessions' devices are listed under"""
import pytest

from app.utils import devices
from app.utils.devices import USER_AGENT_PARSE_LIMIT, device_name

FIREFOX_WINDOWS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0'
EDGE_MAC = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0')
SAFARI_IPHONE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 '
                 '(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1')
CHROME_ANDROID = ('Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/140.0.0.0 Mobile Safari/537.36')


@pytest.mark.parametrize(('user_agent', 'name'), [
    (FIREFOX_WINDOWS, 'Firefox on Windows'),
    (EDGE_MAC, 'Edge on macOS'),
    (SAFARI_IPHONE, 'Mobile Safari on iOS'),
    (CHROME_ANDROID, 'Chrome Mobile on Android'),
], ids=['firefox', 'edge', 'safari', 'chrome'])
def test_names_the_browser_and_the_system(user_agent, name):
    assert device_name(user_agent) == name


@pytest.mark.parametrize(('user_agent', 'name'), [
    ('curl/8.0', 'curl'),
    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'A browser on Windows'),
    ('', 'Unknown device'),
    (None, 'Unknown device'),
    ('not a browser at all', 'Unknown device'),
], ids=['a client without a system', 'a system without a browser', 'empty', 'none', 'nonsense'])
def test_names_as_much_as_it_can(user_agent, name):
    assert device_name(user_agent) == name


def test_parses_only_the_start_of_a_long_user_agent(monkeypatch):
    """The parser's regular expressions run on a request's time"""
    seen = []
    real_parse = devices.ua_parser.parse
    monkeypatch.setattr(devices.ua_parser, 'parse', lambda text: seen.append(text) or real_parse(text))

    assert device_name(FIREFOX_WINDOWS + 'x' * 10_000) == 'Firefox on Windows'
    assert [len(text) for text in seen] == [USER_AGENT_PARSE_LIMIT]
