import unicodedata

# Unicode general categories user text may use: letters, combining marks,
# numbers, punctuation, math, currency and modifier symbols, and spaces. Left
# out: "other symbols", which hold every emoji along with signs like © and °,
# enclosing marks (keycaps), line and paragraph separators, and control,
# format (the zero-width joiner that builds emoji sequences), private-use and
# unassigned characters. frontend/src/utils/validation.ts mirrors this.
_ALLOWED_CATEGORIES = {'Lu', 'Ll', 'Lt', 'Lm', 'Lo', 'Mn', 'Mc', 'Nd', 'Nl', 'No',
                       'Pc', 'Pd', 'Ps', 'Pe', 'Pi', 'Pf', 'Po', 'Sm', 'Sc', 'Sk', 'Zs'}
# Combining marks, but they only turn the character before them into emoji
_VARIATION_SELECTORS = range(0xFE00, 0xFE10)

UNSUPPORTED_CHARACTERS_MESSAGE = 'must not contain emoji or other symbols like © or °'


def is_plain_text(value: str) -> bool:
    """Whether every character of value is one the app accepts.

    Only the Basic Multilingual Plane: what lies beyond it is mostly emoji
    and historic scripts, and leaving it out makes every character one UTF-16
    unit, so the browser's lengths (String.length, maxLength) count what
    Python and MySQL count.
    """
    return all(ord(c) <= 0xFFFF and ord(c) not in _VARIATION_SELECTORS
               and unicodedata.category(c) in _ALLOWED_CATEGORIES for c in value)
