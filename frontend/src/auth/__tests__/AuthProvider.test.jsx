import { describe, it, expect } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { CancelledError, useQueryClient } from '@tanstack/react-query'
import { AuthProvider } from '../AuthProvider'
import { useAuth } from '../useAuth'
import { storage } from '../storage'
import { signIn } from '@/test/router'

const renderAuth = () =>
  renderHook(() => useAuth(), { wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider> })

describe('AuthProvider', () => {
  it('starts signed out when nothing is stored', () => {
    const { result } = renderAuth()

    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.email).toBeNull()
  })

  it('picks up a stored session, as after a page load', () => {
    signIn('stored@example.com')

    const { result } = renderAuth()

    expect(result.current.isAuthenticated).toBe(true)
    expect(result.current.email).toBe('stored@example.com')
  })

  it('login stores the session and signs in, forgetting an ended one', () => {
    storage.endSession()
    const { result } = renderAuth()

    act(() => result.current.login('access', 'csrf', 'user@example.com'))

    expect(result.current.isAuthenticated).toBe(true)
    expect(result.current.sessionEnded).toBe(false)
    expect(result.current.email).toBe('user@example.com')
    expect(storage.getAccessToken()).toBe('access')
    expect(storage.getRefreshCsrf()).toBe('csrf')
  })

  it('logout clears the stored session and signs out', () => {
    signIn()
    const { result } = renderAuth()

    act(() => result.current.logout())

    expect(result.current.isAuthenticated).toBe(false)
    // Logging out on purpose is no news to the user
    expect(result.current.sessionEnded).toBe(false)
    expect(result.current.email).toBeNull()
    expect(storage.getRefreshCsrf()).toBeNull()
  })

  // The api client ends a session in storage when a refresh fails
  it('signs out, and says the session ended, when it ends outside React', () => {
    signIn()
    const { result } = renderAuth()

    act(() => storage.endSession())

    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.sessionEnded).toBe(true)
  })

  it('follows another tab signing in and out', () => {
    const { result } = renderAuth()
    // Another tab writes localStorage directly; this tab hears a storage event
    const otherTab = (change) => act(() => {
      change()
      window.dispatchEvent(new StorageEvent('storage'))
    })

    otherTab(() => localStorage.setItem('access_token', 'other-tab-token'))
    expect(result.current.isAuthenticated).toBe(true)

    otherTab(() => localStorage.clear())
    expect(result.current.isAuthenticated).toBe(false)
  })

  describe('the cache of server data', () => {
    const KEY = ['notes']
    // Another tab writes localStorage directly; this tab hears a storage event
    const otherTab = change => {
      change()
      window.dispatchEvent(new StorageEvent('storage'))
    }

    function renderWithCache() {
      signIn('first@example.com')
      const { result } = renderHook(() => useQueryClient(), {
        wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
      })
      const client = result.current
      client.setQueryData(KEY, 'notes of first@example.com')
      return client
    }

    it.each([
      ['a logout', () => storage.clearAuth()],
      ['a session that ends on its own', () => storage.endSession()],
      ['another tab signing out', () => otherTab(() => localStorage.clear())],
      ['another tab signing in as someone else', () =>
        otherTab(() => localStorage.setItem('email', 'second@example.com'))],
    ])('is emptied by %s, so the next user never sees it', (_, change) => {
      const client = renderWithCache()

      act(change)

      expect(client.getQueryData(KEY)).toBeUndefined()
    })

    it.each([
      ['here', () => storage.setAccessToken('refreshed-token')],
      ['in another tab', () => otherTab(() => localStorage.setItem('access_token', 'refreshed-token'))],
    ])('is kept when the access token is refreshed %s', (_, refresh) => {
      const client = renderWithCache()

      act(refresh)

      expect(client.getQueryData(KEY)).toBe('notes of first@example.com')
    })

    // Emptying it cancels the request still in flight, so its late answer
    // lands nowhere
    it('stays empty when a response from before the logout arrives after it', async () => {
      const client = renderWithCache()
      let respond
      const fetching = client.fetchQuery({
        queryKey: ['account'],
        queryFn: () => new Promise(resolve => { respond = resolve }),
      })

      act(() => storage.clearAuth())
      respond('account of first@example.com')

      await expect(fetching).rejects.toBeInstanceOf(CancelledError)

      expect(client.getQueryData(['account'])).toBeUndefined()
    })
  })
})
