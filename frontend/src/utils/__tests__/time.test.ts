import { describe, it, expect } from 'vitest'
import { hours } from '../time'

describe('hours', () => {
  it.each([
    [1, '1 hour'],
    [24, '24 hours'],
  ])('says %i as %s, as the emails do', (count, said) => {
    expect(hours(count)).toBe(said)
  })
})
