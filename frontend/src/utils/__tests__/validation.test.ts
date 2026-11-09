import { describe, it, expect } from 'vitest'
import { backendConstant } from '@/test/backend'
import {
  hasUnsupportedCharacters,
  validatePassword,
  validateEmail,
  validatePasswordMatch,
  PASSWORD_MIN_LENGTH,
  PASSWORD_MAX_LENGTH,
  PASSWORD_INPUT_MAX_LENGTH,
  EMAIL_MAX_LENGTH
} from '../validation'

describe('validatePassword', () => {
  it.each([
    ['the minimum length', 'a'.repeat(PASSWORD_MIN_LENGTH)],
    ['the maximum length', 'a'.repeat(PASSWORD_MAX_LENGTH)],
    ['a passphrase with spaces', 'correct horse battery staple'],
    ['one kind of character alone', '123456789012345'],
    ['special characters', '!@#$%^&*()_+-=[]{};:\'",.<>/?\\|`~'],
    ['letters and symbols of any language', 'Ünïcödé 日本語 €£ ©°'],
    // Each emoji is one character, though it takes two UTF-16 units
    ['emoji', '😀'.repeat(PASSWORD_MIN_LENGTH)],
    ['joined emoji', '👨‍👩‍👧 family of three'],
    ['the maximum length in emoji', '😀'.repeat(PASSWORD_MAX_LENGTH)],
    // 3 characters as typed, but NFKC expands each ㌕ to the five of キログラム
    ['one that is long enough once normalized', '㌕㌕㌕'],
  ])('accepts %s', (_, password) => {
    expect(validatePassword(password)).toBeUndefined()
  })

  it('requires a password', () => {
    expect(validatePassword('')).toBe('Password is required')
  })

  it.each([
    ['too short', 'a'.repeat(PASSWORD_MIN_LENGTH - 1),
      `Password must be at least ${PASSWORD_MIN_LENGTH} characters`],
    // Long enough in UTF-16 units, as .length counts, but not in characters
    ['too short in emoji', '😀'.repeat(PASSWORD_MIN_LENGTH - 1),
      `Password must be at least ${PASSWORD_MIN_LENGTH} characters`],
    ['too long', 'a'.repeat(PASSWORD_MAX_LENGTH + 1),
      `Password must be at most ${PASSWORD_MAX_LENGTH} characters`],
    // 128 characters as typed, but NFKC expands ㌕ to the five of キログラム
    ['that grows too long when normalized', 'a'.repeat(PASSWORD_MAX_LENGTH - 1) + '㌕',
      `Password must be at most ${PASSWORD_MAX_LENGTH} characters`],
    ...['\t', '\n', '\u0000', '\u007f'].map(control =>
      [`with ${JSON.stringify(control)}`, `a long enough password${control}`,
        'Password must not contain control characters, such as a tab']),
  ])('rejects a password %s', (_, password, message) => {
    expect(validatePassword(password)).toBe(message)
  })

  // The form shows one message at a time, so the order is what the user sees
  it('reports the length before a control character', () => {
    expect(validatePassword('short\t')).toBe(`Password must be at least ${PASSWORD_MIN_LENGTH} characters`)
  })

  it('lets a field hold the longest password in emoji', () => {
    expect('😀'.repeat(PASSWORD_MAX_LENGTH).length).toBe(PASSWORD_INPUT_MAX_LENGTH)
  })
})

describe('validateEmail', () => {
  it.each([
    'user@example.com',
    'user@mail.example.com',
    'user123@example.com',
    'first.last@example.com',
    'user+tag@example.com',
    'user-name@example.com',
    'user_name@example.com',
    // An international domain is fine; the backend stores its ASCII form
    'user@bücher.de',
    'user@xn--bcher-kva.de',
  ])('accepts %s', (email) => {
    expect(validateEmail(email)).toBeUndefined()
  })

  it('requires an email', () => {
    expect(validateEmail('')).toBe('Email is required')
  })

  it.each([
    'userexample.com',
    'user@',
    '@example.com',
    'user@example',
    'user name@example.com',
    'user@@example.com',
    '@',
    // A plain address only: no display name, quoting or IP literal
    'Name <user@example.com>',
    '<user@example.com>',
    '"user name"@example.com',
    'user@[192.0.2.1]',
    'user..name@example.com',
    '.user@example.com',
    'user@-example.com',
    'user@example..com',
    'user@😀.com',
  ])('rejects %s as malformed', (email) => {
    expect(validateEmail(email)).toBe('Please enter a valid email address')
  })

  it('rejects an email longer than the users.email column', () => {
    expect(validateEmail('a'.repeat(EMAIL_MAX_LENGTH) + '@example.com'))
      .toBe(`Email must be at most ${EMAIL_MAX_LENGTH} characters`)
  })

  it.each(['josé@example.com', '😀@example.com'])('explains that %s needs an ASCII local part', (email) => {
    expect(validateEmail(email)).toBe(
      'Before the @, an email can use only English letters, numbers and symbols like . _ + -')
  })

  it('counts the length of the ASCII form the backend stores', () => {
    const domain = 'ü'.repeat(50) + '.de'
    const email = 'a'.repeat(EMAIL_MAX_LENGTH - domain.length - 1) + '@' + domain
    expect(email.length).toBe(EMAIL_MAX_LENGTH)

    expect(validateEmail(email)).toBe(`Email must be at most ${EMAIL_MAX_LENGTH} characters`)
  })
})

// Every free-text field but passwords, mirroring backend/app/utils/text.py
describe('hasUnsupportedCharacters', () => {
  it.each([
    'plain words and punctuation!',
    'letters of any language: éßøñ 日本語',
    'math, currency and modifier symbols: ×÷± €£¥ ^`',
    'spaces of every kind:  　',
  ])('accepts %s', (text) => {
    expect(hasUnsupportedCharacters(text)).toBe(false)
  })

  it.each([
    '😀', '❤', '🇺🇸', '1⃣', '\u{FE0F}', '\u{1F3FB}', '\u{200D}', '©', '°', '\u0000',
    // A CJK letter beyond the Basic Multilingual Plane
    '𠀀',
  ])('refuses %j', (symbol) => {
    expect(hasUnsupportedCharacters(`some text ${symbol}`)).toBe(true)
  })
})

describe('validatePasswordMatch', () => {
  it.each([
    ['Password123', 'Password123'],
    ['', ''],
    ['Pass word 123', 'Pass word 123'],
  ])('accepts %o twice', (password, confirm) => {
    expect(validatePasswordMatch(password, confirm)).toBeUndefined()
  })

  it.each([
    ['Password123', 'Password456'],
    ['Password123', 'password123'],
    ['Password123', 'Password123 '],
    ['Password123', ''],
    ['', 'Password123'],
  ])('rejects %o and %o', (password, confirm) => {
    expect(validatePasswordMatch(password, confirm)).toBe('Passwords do not match')
  })
})

// The backend's limits are the real ones; these only spare the user a round
// trip. Read from its source, so changing one side alone fails here.
describe('limits match the backend', () => {
  it.each([
    ['PASSWORD_MIN_LENGTH', PASSWORD_MIN_LENGTH, 'auth/schemas.py'],
    ['PASSWORD_MAX_LENGTH', PASSWORD_MAX_LENGTH, 'auth/schemas.py'],
    ['EMAIL_MAX_LENGTH', EMAIL_MAX_LENGTH, 'auth/models.py'],
  ])('%s', (name, value, file) => {
    expect(value).toBe(backendConstant(file, name))
  })
})
