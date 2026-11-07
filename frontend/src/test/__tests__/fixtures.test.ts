import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'fs'
import path from 'path'
import { BACKEND_APP } from '../backend'
import { ERROR_CODES } from '@/api/errors'
import { errorBody } from '../fixtures'

function backendErrorCodes() {
  const codes = new Set<string>()
  for (const entry of readdirSync(BACKEND_APP, { recursive: true, encoding: 'utf8' })) {
    if (!entry.endsWith('.py')) continue
    const source = readFileSync(path.join(BACKEND_APP, entry), 'utf8')
    for (const [, code] of source.matchAll(/code='([A-Z_]+)'/g)) {
      if (code) codes.add(code)
    }
  }
  return [...codes].sort()
}

describe('test fixtures', () => {
  it('know exactly the error codes the backend sends', () => {
    expect([...ERROR_CODES].sort()).toEqual(backendErrorCodes())
  })

  it('refuse an error code the backend never sends', () => {
    // @ts-expect-error: the type check refuses it too
    expect(() => errorBody('EMAIL_ALREADY_EXISTS')).toThrow(/never sends/)
  })
})
