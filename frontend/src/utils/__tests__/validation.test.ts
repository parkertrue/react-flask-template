import { describe, it, expect } from 'vitest'
import { backendConstant } from '@/test/backend'
import {
  validatePassword,
  validateEmail,
  validatePasswordMatch,
  PASSWORD_MIN_LENGTH,
  PASSWORD_MAX_LENGTH,
  EMAIL_MAX_LENGTH
} from '../validation'

describe('validatePassword', () => {
  it.each([
    ['all requirements met', 'Password123'],
    ['the minimum length', 'Pass123!'],
    ['the maximum length', 'A'.repeat(63) + 'a'.repeat(63) + '12'],
    ['special characters', 'P@ssw0rd!'],
    ['letters, punctuation and symbols of any language', 'Password123€£éß日本×÷'],
    // NFKC turns full-width letters and digits into plain ones
    ['full-width letters', 'Ｐassword１２３'],
    // 4 characters as typed, but NFKC expands ㌕ to the five of キログラム
    ['one that is long enough once normalized', 'Aa1㌕'],
  ])('accepts %s', (_, password) => {
    expect(validatePassword(password)).toBeUndefined()
  })

  it('requires a password', () => {
    expect(validatePassword('')).toBe('Password is required')
  })

  it.each([
    ['too short', 'Pass1', `Password must be at least ${PASSWORD_MIN_LENGTH} characters`],
    ['too long', 'Aa1' + 'x'.repeat(PASSWORD_MAX_LENGTH - 2),
      `Password must be at most ${PASSWORD_MAX_LENGTH} characters`],
    ['without an uppercase letter', 'password123', 'Password must contain at least one uppercase letter'],
    ['without a lowercase letter', 'PASSWORD123', 'Password must contain at least one lowercase letter'],
    ['without a number', 'Password', 'Password must contain at least one number'],
    ...[' ', '\t', ' ', '　'].map(space =>
      [`with ${JSON.stringify(space)}`, `Pass${space}word123`, 'Password must not contain spaces']),
    ...['😀', '❤', '🇺🇸', '1⃣', '️', '\u{1F3FB}', '‍', '©', '°',
      // A CJK letter beyond the Basic Multilingual Plane
      '𠀀'].map(symbol =>
      [`with ${JSON.stringify(symbol)}`, `Password123${symbol}`,
        'Password must not contain emoji or other symbols like © or °']),
    // 128 characters as typed, but NFKC expands ㌕ to the five of キログラム
    ['that grows too long when normalized', 'Aa1' + 'x'.repeat(PASSWORD_MAX_LENGTH - 4) + '㌕',
      `Password must be at most ${PASSWORD_MAX_LENGTH} characters`],
  ])('rejects a password %s', (_, password, message) => {
    expect(validatePassword(password)).toBe(message)
  })

  // The form shows one message at a time, so the order is what the user sees
  it.each([
    ['pass', `Password must be at least ${PASSWORD_MIN_LENGTH} characters`],
    ['pass word😀', 'Password must not contain spaces'],
    ['password', 'Password must contain at least one uppercase letter'],
  ])('reports only the first rule %o breaks', (password, message) => {
    expect(validatePassword(password)).toBe(message)
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
