import { describe, it, expect, vi } from 'vitest'
import {
  requestRegistration, completeRegistration, loginUser, logoutUser, logoutAllDevices,
  clearAuthCookies, deleteAccount, getAccount, exportAccountData,
} from '../authService'
import { api } from '@/api/api'
import { account, dataExport, tokens } from '@/test/fixtures'

vi.mock('@/api/api')

// Thin wrappers over the api client: each must hit the right endpoint with
// the right body, and hand back what callers use. Interceptors, refresh and
// CSRF headers are api.test.ts's job.
describe('authService', () => {
  it.each([
    ['requestRegistration', () => requestRegistration('a@example.com'),
      '/auth/register', { email: 'a@example.com' }],
    ['completeRegistration', () => completeRegistration('a-token', 'Password123', 1),
      '/auth/register/complete', { token: 'a-token', password: 'Password123', terms_version: 1 }],
    ['loginUser', () => loginUser('a@example.com', 'Password123'),
      '/auth/login', { email: 'a@example.com', password: 'Password123' }],
    ['logoutUser', () => logoutUser(), '/auth/logout', undefined],
    ['logoutAllDevices', () => logoutAllDevices(), '/auth/logout-all', undefined],
    ['deleteAccount', () => deleteAccount('Password123'), '/account/delete', { password: 'Password123' }],
    // A JSON body, so another site cannot send it without a CORS preflight
    ['clearAuthCookies', () => clearAuthCookies(), '/auth/clear-cookies', {}],
  ])('%s posts to the right endpoint', async (_, call, path, body) => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })

    await call()

    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post).toHaveBeenCalledWith(path, ...(body === undefined ? [] : [body]))
  })

  it.each([
    ['getAccount', getAccount, '/account', account()],
    ['exportAccountData', exportAccountData, '/account/export', dataExport()],
  ])('%s gets the right endpoint and returns its body', async (_, call, path, body) => {
    vi.mocked(api.get).mockResolvedValue({ data: body })

    expect(await call()).toEqual(body)
    expect(api.get).toHaveBeenCalledExactlyOnceWith(path)
  })

  it.each([
    ['loginUser', () => loginUser('a@example.com', 'Password123')],
    ['completeRegistration', () => completeRegistration('a-token', 'Password123', 1)],
  ])('%s returns the tokens the backend issued', async (_, call) => {
    vi.mocked(api.post).mockResolvedValue({ data: tokens('access', 'csrf') })

    expect(await call()).toEqual(tokens('access', 'csrf'))
  })

  it.each([
    ['requestRegistration', () => requestRegistration('a@example.com')],
    ['completeRegistration', () => completeRegistration('a-token', 'Password123', 1)],
    ['loginUser', () => loginUser('a@example.com', 'Password123')],
    ['logoutUser', () => logoutUser()],
    ['logoutAllDevices', () => logoutAllDevices()],
    ['deleteAccount', () => deleteAccount('Password123')],
  ])(
    '%s passes failures on to the caller untouched',
    async (_, call) => {
      const error = new Error('Request failed')
      vi.mocked(api.post).mockRejectedValue(error)

      await expect(call()).rejects.toBe(error)
    }
  )

  // Its callers are already ending the session, with nothing left to try
  it('clearAuthCookies swallows a failure', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('Request failed'))

    await expect(clearAuthCookies()).resolves.toBeUndefined()
  })
})
