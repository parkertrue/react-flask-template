import { describe, it, expect } from 'vitest'
import { readLink, tokenEmail } from '../emailLink'
import { linkToken } from '@/test/fixtures'

// What the backend signs: base64url JSON, then the time and the signature
function signed(payload: unknown) {
  const encoded = btoa(JSON.stringify(payload)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
  return `${encoded}.aTime.aSignature`
}

describe('tokenEmail', () => {
  // Their payloads hold base64url's own characters, '_' and '-'
  it.each(['user@example.com', 'user?@example.com', 'user~@example.com'])('reads %s', email => {
    expect(tokenEmail(linkToken(email, 'a1b2'))).toBe(email)
  })

  it.each([
    ['no token', null],
    ['compressed', '.eJyrVkpUslIqLU4tUqoFAB2bBHU.aTime.aSignature'],
    ['not a token', 'garbage'],
    ['an address alone', signed('user@example.com')],
    ['an address that is not text', signed([1, ''])],
    ['an object', signed({ email: 'user@example.com' })],
  ])('reads no address from %s', (_, token) => {
    expect(tokenEmail(token)).toBe('')
  })
})

describe('readLink', () => {
  it("reads the fragment's token, and the address it names, never the fragment's", () => {
    const token = linkToken('attacker@example.com')

    expect(readLink(`#email=victim%40example.com&token=${token}`))
      .toEqual({ token, email: 'attacker@example.com' })
  })

  it('reads nothing from a fragment without a token', () => {
    expect(readLink('')).toEqual({ token: null, email: '' })
  })
})
