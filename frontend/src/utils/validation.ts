// Counted in characters (code points), as the backend counts them
export const PASSWORD_MIN_LENGTH = 15
export const PASSWORD_MAX_LENGTH = 128
// A password field's maxLength, which counts UTF-16 units: an emoji takes
// two, so a password of PASSWORD_MAX_LENGTH emoji still fits. Past the limit
// itself, validatePassword says so.
export const PASSWORD_INPUT_MAX_LENGTH = PASSWORD_MAX_LENGTH * 2
export const EMAIL_MAX_LENGTH = 128

// A character no user text may contain, mirroring backend/app/utils/text.py:
// anything but a letter, combining mark, number, punctuation, math, currency
// or modifier symbol, or space (so no emoji, nor © or °), an emoji variation
// selector, or anything beyond the Basic Multilingual Plane. Without the
// last, every character is one UTF-16 unit, so String.length and maxLength
// count what the backend counts.
const UNSUPPORTED_CHARACTER =
  /[^\p{L}\p{Mn}\p{Mc}\p{N}\p{P}\p{Sm}\p{Sc}\p{Sk}\p{Zs}]|[\uFE00-\uFE0F]|[\u{10000}-\u{10FFFF}]/u

export const hasUnsupportedCharacters = (text: string) => UNSUPPORTED_CHARACTER.test(text)

export const UNSUPPORTED_CHARACTERS_MESSAGE = 'must not contain emoji or other symbols like © or °'

/**
 * Validate a password as the backend does, wherever one is typed
 * (registration, login and account deletion): 15-128 characters after NFKC
 * normalization, counted in code points, so an emoji is one; any script,
 * spaces and emoji welcome; no control characters such as a tab. Nothing is
 * asked of which kinds of character it holds (NIST SP 800-63B).
 */
export function validatePassword(password: string): string | undefined {
  if (!password) {
    return 'Password is required'
  }

  const normalized = password.normalize('NFKC')
  const length = Array.from(normalized).length

  if (length < PASSWORD_MIN_LENGTH) {
    return `Password must be at least ${PASSWORD_MIN_LENGTH} characters`
  }

  if (length > PASSWORD_MAX_LENGTH) {
    return `Password must be at most ${PASSWORD_MAX_LENGTH} characters`
  }

  if (/\p{Cc}/u.test(normalized)) {
    return 'Password must not contain control characters, such as a tab'
  }

  return undefined
}

// RFC 5322's unquoted local part, in ASCII only: anything else before the @
// needs SMTPUTF8, which many mail servers lack
const EMAIL_LOCAL = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/
// A domain label of any script's letters and digits, with inner hyphens. No
// emoji, which IDNA refuses.
const DOMAIN_LABEL = /^[\p{L}\p{M}\p{N}]([\p{L}\p{M}\p{N}-]*[\p{L}\p{M}\p{N}])?$/u

// The address as the backend stores it: an international domain in its
// ASCII form (bücher.de -> xn--bcher-kva.de), which the URL parser computes
function asciiEmail(local: string, domain: string) {
  try {
    return `${local}@${new URL(`http://${domain}`).hostname}`
  } catch {
    return null
  }
}

/**
 * Validate email format: a plain local@domain.tld address, no display name,
 * with an ASCII local part. The backend's check is the full one; this only
 * spares the user a round trip.
 */
export function validateEmail(email: string): string | undefined {
  if (!email) {
    return 'Email is required'
  }

  const parts = email.split('@')
  // Both are set when there is exactly one @
  const [local = '', domain = ''] = parts
  const labels = domain.split('.')
  const stored = parts.length === 2 ? asciiEmail(local, domain) : null

  if ((stored ?? email).length > EMAIL_MAX_LENGTH) {
    return `Email must be at most ${EMAIL_MAX_LENGTH} characters`
  }

  if (parts.length === 2 && /\P{ASCII}/u.test(local)) {
    return 'Before the @, an email can use only English letters, numbers and symbols like . _ + -'
  }

  if (parts.length !== 2 || !EMAIL_LOCAL.test(local) || labels.length < 2 ||
      !labels.every(label => DOMAIN_LABEL.test(label)) || stored === null) {
    return 'Please enter a valid email address'
  }

  return undefined
}

export function validatePasswordMatch(password: string, confirmPassword: string): string | undefined {
  if (password !== confirmPassword) {
    return 'Passwords do not match'
  }

  return undefined
}
