import { describe, it, expect, vi } from 'vitest'
import {
  requestRegistration, completeRegistration, loginUser, logoutUser, logoutAllDevices,
  clearAuthCookies, deleteAccount, getAccount, exportAccountData, REGISTRATION_LINK_HOURS,
  requestPasswordReset, completePasswordReset, PASSWORD_RESET_LINK_HOURS,
  requestEmailChange, completeEmailChange, undoEmailChange, EMAIL_CHANGE_LINK_HOURS,
} from '../authService'
import { api } from '@/api/api'
import { backendConstant } from '@/test/backend'
import { account, dataExport, tokens } from '@/test/fixtures'

vi.mock('@/api/api')

// Thin wrappers over the api client: each must hit the right endpoint with
// the right body, and hand back what callers use. Interceptors, refresh and
// CSRF headers are api.test.ts's job.
// The page that says how long the emailed link works says what the backend
// mints it for
it.each([
  ['sign-up', REGISTRATION_LINK_HOURS, 'auth/emails.py', 'REGISTRATION_LINK_HOURS'],
  ['password reset', PASSWORD_RESET_LINK_HOURS, 'auth/emails.py', 'PASSWORD_RESET_LINK_HOURS'],
  ['email change', EMAIL_CHANGE_LINK_HOURS, 'account/emails.py', 'EMAIL_CHANGE_LINK_HOURS'],
])('gives the %s link the lifetime the backend does', (_, hours, file, name) => {
  expect(hours).toBe(backendConstant(file, name))
})

describe('authService', () => {
  it.each([
    ['requestRegistration', () => requestRegistration('a@example.com'),
      '/auth/register', { email: 'a@example.com' }],
    ['completeRegistration', () => completeRegistration('a-token', 'a valid passphrase', 1),
      '/auth/register/complete', { token: 'a-token', password: 'a valid passphrase', terms_version: 1 }],
    ['requestPasswordReset', () => requestPasswordReset('a@example.com'),
      '/auth/password-reset', { email: 'a@example.com' }],
    ['completePasswordReset', () => completePasswordReset('a-token', 'a valid passphrase'),
      '/auth/password-reset/complete', { token: 'a-token', password: 'a valid passphrase' }],
    ['loginUser', () => loginUser('a@example.com', 'a valid passphrase'),
      '/auth/login', { email: 'a@example.com', password: 'a valid passphrase' }],
    ['requestEmailChange', () => requestEmailChange('b@example.com', 'a valid passphrase'),
      '/account/email', { email: 'b@example.com', password: 'a valid passphrase' }],
    ['completeEmailChange', () => completeEmailChange('a-token'), '/account/email/complete', { token: 'a-token' }],
    ['undoEmailChange', () => undoEmailChange('a-token'), '/account/email/undo', { token: 'a-token' }],
    ['logoutUser', () => logoutUser(), '/auth/logout', undefined],
    ['logoutAllDevices', () => logoutAllDevices(), '/auth/logout-all', undefined],
    ['deleteAccount', () => deleteAccount('a valid passphrase'), '/account/delete', { password: 'a valid passphrase' }],
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
    ['loginUser', () => loginUser('a@example.com', 'a valid passphrase')],
    ['completeRegistration', () => completeRegistration('a-token', 'a valid passphrase', 1)],
  ])('%s returns the tokens the backend issued', async (_, call) => {
    vi.mocked(api.post).mockResolvedValue({ data: tokens('access', 'csrf') })

    expect(await call()).toEqual(tokens('access', 'csrf'))
  })

  it.each([
    ['requestRegistration', () => requestRegistration('a@example.com')],
    ['completeRegistration', () => completeRegistration('a-token', 'a valid passphrase', 1)],
    ['requestPasswordReset', () => requestPasswordReset('a@example.com')],
    ['completePasswordReset', () => completePasswordReset('a-token', 'a valid passphrase')],
    ['requestEmailChange', () => requestEmailChange('b@example.com', 'a valid passphrase')],
    ['completeEmailChange', () => completeEmailChange('a-token')],
    ['undoEmailChange', () => undoEmailChange('a-token')],
    ['loginUser', () => loginUser('a@example.com', 'a valid passphrase')],
    ['logoutUser', () => logoutUser()],
    ['logoutAllDevices', () => logoutAllDevices()],
    ['deleteAccount', () => deleteAccount('a valid passphrase')],
  ])(
    '%s passes failures on to the caller untouched',
    async (_, call) => {
      const error = new Error('Request failed')
      vi.mocked(api.post).mockRejectedValue(error)

      await expect(call()).rejects.toBe(error)
    }
  )

  it.each([
    ['completeEmailChange', completeEmailChange],
    ['undoEmailChange', undoEmailChange],
  ])("%s returns the account's address now", async (_, call) => {
    vi.mocked(api.post).mockResolvedValue({ data: { email: 'b@example.com' } })

    expect(await call('a-token')).toEqual({ email: 'b@example.com' })
  })

  // Its callers are already ending the session, with nothing left to try
  it('clearAuthCookies swallows a failure', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('Request failed'))

    await expect(clearAuthCookies()).resolves.toBeUndefined()
  })
})
