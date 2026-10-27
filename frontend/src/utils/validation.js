export const PASSWORD_MIN_LENGTH = 8
export const PASSWORD_MAX_LENGTH = 128
export const EMAIL_MAX_LENGTH = 128

// A character no user text may contain, mirroring backend/app/utils/text.py:
// anything but a letter, combining mark, number, punctuation, math, currency
// or modifier symbol, or space (so no emoji, nor © or °), an emoji variation
// selector, or anything beyond the Basic Multilingual Plane. Without the
// last, every character is one UTF-16 unit, so String.length and maxLength
// count what the backend counts.
const UNSUPPORTED_CHARACTER =
  /[^\p{L}\p{Mn}\p{Mc}\p{N}\p{P}\p{Sm}\p{Sc}\p{Sk}\p{Zs}]|[\uFE00-\uFE0F]|[\u{10000}-\u{10FFFF}]/u

export const hasUnsupportedCharacters = text => UNSUPPORTED_CHARACTER.test(text)

export const UNSUPPORTED_CHARACTERS_MESSAGE = 'must not contain emoji or other symbols like © or °'

/**
 * Validate password meets all requirements: 8-128 characters with an
 * uppercase letter, a lowercase letter and a number, and no spaces or emoji.
 * Checked as the backend checks it, after NFKC normalization, and wherever a
 * password is typed: registration, login and account deletion.
 */
export function validatePassword(password) {
  if (!password) {
    return 'Password is required'
  }

  const normalized = password.normalize('NFKC')

  if (normalized.length < PASSWORD_MIN_LENGTH) {
    return `Password must be at least ${PASSWORD_MIN_LENGTH} characters`
  }

  if (normalized.length > PASSWORD_MAX_LENGTH) {
    return `Password must be at most ${PASSWORD_MAX_LENGTH} characters`
  }

  if (/\s/u.test(normalized)) {
    return 'Password must not contain spaces'
  }

  if (hasUnsupportedCharacters(normalized)) {
    return `Password ${UNSUPPORTED_CHARACTERS_MESSAGE}`
  }

  if (!/[A-Z]/.test(normalized)) {
    return 'Password must contain at least one uppercase letter'
  }

  if (!/[a-z]/.test(normalized)) {
    return 'Password must contain at least one lowercase letter'
  }

  if (!/[0-9]/.test(normalized)) {
    return 'Password must contain at least one number'
  }
}

// RFC 5322's unquoted local part, in ASCII only: anything else before the @
// needs SMTPUTF8, which many mail servers lack
const EMAIL_LOCAL = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/
// A domain label of any script's letters and digits, with inner hyphens. No
// emoji, which IDNA refuses.
const DOMAIN_LABEL = /^[\p{L}\p{M}\p{N}]([\p{L}\p{M}\p{N}-]*[\p{L}\p{M}\p{N}])?$/u

// The address as the backend stores it: an international domain in its
// ASCII form (bücher.de -> xn--bcher-kva.de), which the URL parser computes
function asciiEmail(local, domain) {
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
export function validateEmail(email) {
  if (!email) {
    return 'Email is required'
  }

  const parts = email.split('@')
  const [local, domain] = parts
  const labels = domain?.split('.') ?? []
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
}

export function validatePasswordMatch(password, confirmPassword) {
  if (password !== confirmPassword) {
    return 'Passwords do not match'
  }
}
