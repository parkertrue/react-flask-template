import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { apiTypes, SCHEMAS_TS } from '../apiTypes'

describe('src/api/schemas.ts', () => {
  // The backend's tests/unit/test_export_schemas.py checks schemas.json the
  // same way, so the two halves cannot drift apart
  it('is what schemas.json generates', { timeout: 30_000 }, async () => {
    // A Windows checkout's CRLF is no difference
    const committed = readFileSync(SCHEMAS_TS, 'utf8').replaceAll('\r\n', '\n')

    expect(committed, 'run `npm run api-types`').toBe(await apiTypes())
  })
})
