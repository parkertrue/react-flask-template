import { describe, it, expect, beforeEach, vi } from 'vitest'
import { storage } from '../storage'

describe('storage utility', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('Access Token', () => {
    it('should store and retrieve access token', () => {
      const token = 'test-access-token'
      storage.setAccessToken(token)
      expect(storage.getAccessToken()).toBe(token)
    })

    it('should remove access token when set to null', () => {
      storage.setAccessToken('test-token')
      storage.setAccessToken(null)
      expect(storage.getAccessToken()).toBeNull()
    })
  })

  describe('CSRF Token', () => {
    it('should store and retrieve CSRF token', () => {
      const csrf = 'test-csrf-token'
      storage.setRefreshCsrf(csrf)
      expect(storage.getRefreshCsrf()).toBe(csrf)
    })

    it('should remove CSRF token when set to null', () => {
      storage.setRefreshCsrf('test-csrf')
      storage.setRefreshCsrf(null)
      expect(storage.getRefreshCsrf()).toBeNull()
    })

    // What a login or refresh hands it when the backend's CSRF check is off
    it('should remove CSRF token when set to undefined', () => {
      storage.setRefreshCsrf('test-csrf')
      storage.setRefreshCsrf(undefined)
      expect(storage.getRefreshCsrf()).toBeNull()
    })
  })

  describe('Email', () => {
    it('should store and retrieve email', () => {
      const email = 'test@example.com'
      storage.setEmail(email)
      expect(storage.getEmail()).toBe(email)
    })

    it('should remove email when set to null', () => {
      storage.setEmail('test@example.com')
      storage.setEmail(null)
      expect(storage.getEmail()).toBeNull()
    })
  })

  describe('clearAuth', () => {
    it('should clear all auth data', () => {
      storage.setAccessToken('token')
      storage.setRefreshCsrf('csrf')
      storage.setEmail('test@example.com')

      storage.clearAuth()

      expect(storage.getAccessToken()).toBeNull()
      expect(storage.getRefreshCsrf()).toBeNull()
      expect(storage.getEmail()).toBeNull()
    })

    it('should not affect other localStorage items', () => {
      localStorage.setItem('other-key', 'other-value')
      storage.setAccessToken('token')

      storage.clearAuth()

      expect(localStorage.getItem('other-key')).toBe('other-value')
    })
  })

  describe('a session that ended on its own', () => {
    it('clears the session and remembers that it ended', () => {
      storage.setAccessToken('token')
      storage.setRefreshCsrf('csrf')
      storage.setEmail('test@example.com')

      storage.endSession()

      expect(storage.getAccessToken()).toBeNull()
      expect(storage.getRefreshCsrf()).toBeNull()
      expect(storage.getEmail()).toBeNull()
      expect(storage.getSessionEnded()).toBe(true)
    })

    it.each([
      ['a logout', () => storage.clearAuth()],
      ['clearSessionEnded', () => storage.clearSessionEnded()],
    ])('is forgotten after %s', (_, forget) => {
      storage.endSession()

      forget()

      expect(storage.getSessionEnded()).toBe(false)
    })
  })

  describe('subscribe', () => {
    it.each([
      ['setAccessToken', () => storage.setAccessToken('token')],
      ['setRefreshCsrf', () => storage.setRefreshCsrf('csrf')],
      ['setEmail', () => storage.setEmail('user@example.com')],
      ['clearAuth', () => storage.clearAuth()],
      ['endSession', () => storage.endSession()],
      ['clearSessionEnded', () => storage.clearSessionEnded()],
    ])('tells the listener about %s', (_, change) => {
      const listener = vi.fn()
      const unsubscribe = storage.subscribe(listener)

      change()

      expect(listener).toHaveBeenCalledTimes(1)
      unsubscribe()
    })

    // The browser fires it when another tab changes localStorage
    it('tells the listener about a storage event', () => {
      const listener = vi.fn()
      const unsubscribe = storage.subscribe(listener)

      window.dispatchEvent(new StorageEvent('storage'))

      expect(listener).toHaveBeenCalledTimes(1)
      unsubscribe()
    })

    it('stops once unsubscribed', () => {
      const listener = vi.fn()
      storage.subscribe(listener)()

      storage.setAccessToken('token')
      window.dispatchEvent(new StorageEvent('storage'))

      expect(listener).not.toHaveBeenCalled()
    })
  })
})
