import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useAuth } from '../useAuth'

describe('useAuth', () => {
  it('refuses to run outside AuthProvider', () => {
    // React logs the error it rethrows; keep the test output clean
    vi.spyOn(console, 'error').mockImplementation(() => {})

    expect(() => renderHook(() => useAuth())).toThrow('useAuth must be used within AuthProvider')
  })
})
