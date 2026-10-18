import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import path from 'path'
import { OPERATOR, TERMS_VERSION } from '../legal'
import { backendConstant } from '@/test/backend'

const securityTxt = readFileSync(
  path.resolve(import.meta.dirname, '../../public/.well-known/security.txt'), 'utf8')
const field = name => securityTxt.match(new RegExp(`^${name}: (.*)$`, 'm'))[1]

describe('legal details', () => {
  it('accept the terms version the backend requires', () => {
    expect(TERMS_VERSION).toBe(backendConstant('auth/models.py', 'TERMS_VERSION'))
  })

  // security.txt can't import legal.js
  it('give security.txt the operator\'s contact email', () => {
    expect(field('Contact')).toBe(`mailto:${OPERATOR.email}`)
  })

  // RFC 9116 wants Expires less than a year away, and a lapsed file is one
  // reporters should ignore. This starts failing 30 days before it lapses,
  // the template's own CI included, so someone renews it in time
  it('give security.txt an expiry date, at least 30 days and at most a year away', () => {
    expect(field('Expires')).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)
    const daysLeft = (Date.parse(field('Expires')) - Date.now()) / 86_400_000
    expect(daysLeft).toBeGreaterThan(30)
    expect(daysLeft).toBeLessThanOrEqual(366)
  })
})
