import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import AccountPage from '../AccountPage'
import ProtectedRoute from '@/auth/ProtectedRoute'
import { storage } from '@/auth/storage'
import { getAccount, logoutAllDevices, clearAuthCookies, deleteAccount } from '@/auth/authService'
import { account, errorBody } from '@/test/fixtures'
import { renderRoutes, signIn } from '@/test/router'
import { APP_NAME } from '@/appName'

vi.mock('@/auth/authService')

// Says whether it was reached from a deleted account, as LoginPage does
function LoginStand() {
  const { state } = useLocation()
  return <p>Login page{state?.accountDeleted && ': account deleted'}</p>
}

// Behind ProtectedRoute, as in the app, where ending the session before home
// has rendered would send it to /login instead
function renderPage() {
  signIn('user@example.com')
  return renderRoutes([
    { element: <ProtectedRoute />, children: [{ path: '/account', element: <AccountPage /> }] },
    { path: '/', element: <p>Home page</p> },
    { path: '/login', element: <LoginStand /> },
  ], '/account')
}

const logoutAll = () => screen.getByRole('button', { name: /log out all devices|logging out/i })

const httpError = (status, code, message) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: code ? errorBody(code, message) : {} },
  })

describe('AccountPage', () => {
  beforeEach(() => {
    getAccount.mockResolvedValue(account('user@example.com', '2026-01-15T10:30:00+00:00'))
    logoutAllDevices.mockResolvedValue()
    clearAuthCookies.mockResolvedValue()
    deleteAccount.mockResolvedValue()
  })

  it('shows who is signed in, then loads when they joined', async () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Account' })).toBeInTheDocument()
    expect(screen.getByText('user@example.com')).toBeInTheDocument()
    expect(document.title).toBe(`Account | ${APP_NAME}`)
    expect(screen.getByRole('status')).toHaveTextContent('Loading account details...')

    // Announced on the same live region that said it was loading
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/^Member since /))
    expect(screen.getByText(/2026/, { selector: 'time' }))
      .toHaveAttribute('dateTime', '2026-01-15T10:30:00+00:00')
    expect(getAccount).toHaveBeenCalledTimes(1)
  })

  it('says so when the account cannot be loaded, and still offers logout everywhere', async () => {
    getAccount.mockRejectedValue(httpError(503, 'SERVICE_UNAVAILABLE', 'Service temporarily unavailable'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Service temporarily unavailable')
    expect(screen.getByRole('status')).toHaveTextContent('')
    expect(logoutAll()).toBeInTheDocument()
  })

  it('signs every device out, ends this session and goes home', async () => {
    const { user, router } = renderPage()

    await user.click(logoutAll())

    expect(await screen.findByText('Home page')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/')
    expect(logoutAllDevices).toHaveBeenCalledTimes(1)
    expect(storage.getAccessToken()).toBeNull()
  })

  // Other devices stay signed in unless the server revoked them, so a
  // failure must say so and leave this session for a retry
  it.each([
    ['the server fails', httpError(503, 'SERVICE_UNAVAILABLE', 'Could not log out other devices'),
      'Could not log out other devices'],
    ['the network fails', new Error('Network Error'), 'Network error'],
  ])('keeps the session and says so when %s', async (_, error, message) => {
    logoutAllDevices.mockRejectedValue(error)
    const { user } = renderPage()

    await user.click(logoutAll())

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(storage.getAccessToken()).toBe('access-token')
    expect(clearAuthCookies).not.toHaveBeenCalled()
    expect(logoutAll()).toHaveAttribute('aria-disabled', 'false')
  })

  it('ends the session when the server says it is already over (401)', async () => {
    logoutAllDevices.mockRejectedValue(httpError(401))
    const { user, router } = renderPage()

    await user.click(logoutAll())

    expect(await screen.findByText('Home page')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/')
    expect(storage.getAccessToken()).toBeNull()
    expect(clearAuthCookies).toHaveBeenCalledTimes(1)
  })

  it('clears an earlier error when trying again', async () => {
    logoutAllDevices.mockRejectedValueOnce(httpError(503, 'SERVICE_UNAVAILABLE'))
    const { user } = renderPage()
    await user.click(logoutAll())
    await screen.findByRole('alert')

    await user.click(logoutAll())

    expect(await screen.findByText('Home page')).toBeInTheDocument()
    expect(logoutAllDevices).toHaveBeenCalledTimes(2)
  })

  it('keeps focus and ignores repeat clicks while the request is in flight', async () => {
    let finish
    logoutAllDevices.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const { user } = renderPage()

    await user.click(logoutAll())
    await user.click(logoutAll())

    expect(logoutAll()).toHaveTextContent('Logging out...')
    expect(logoutAll()).toHaveAttribute('aria-disabled', 'true')
    expect(logoutAll()).toHaveFocus()
    expect(logoutAllDevices).toHaveBeenCalledTimes(1)
    await act(async () => finish())
  })

  describe('deleting the account', () => {
    // jsdom leaves the page behind a modal dialog reachable, so every query
    // of the dialog's own controls is made within it
    const dialog = () => screen.getByRole('dialog', { name: 'Delete your account?' })
    const inDialog = () => within(dialog())
    const passwordField = () => inDialog().getByLabelText('Password')
    const submitButton = () =>
      inDialog().getByRole('button', { name: /^(delete account|deleting\.\.\.)$/i })
    // The page's own, the first in the document
    const pageDeleteButton = () => screen.getAllByRole('button', { name: 'Delete account' })[0]

    async function askToDelete(user, password = 'MyPassword123') {
      await user.click(pageDeleteButton())
      await user.type(passwordField(), password)
    }

    it('asks for the password in a dialog, deleting nothing yet', async () => {
      const { user } = renderPage()

      await user.click(pageDeleteButton())

      expect(dialog()).toHaveAccessibleDescription(/cannot be undone/)
      expect(passwordField()).toHaveFocus()
      expect(passwordField()).toHaveAccessibleDescription('Enter your password to confirm.')
      expect(deleteAccount).not.toHaveBeenCalled()
    })

    it('deletes nothing when the user cancels', async () => {
      const { user } = renderPage()
      await askToDelete(user)

      await user.click(inDialog().getByRole('button', { name: 'Cancel' }))

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(pageDeleteButton()).toHaveFocus()
      expect(deleteAccount).not.toHaveBeenCalled()
      expect(storage.getAccessToken()).toBe('access-token')
    })

    it('asks afresh after a failed try is cancelled', async () => {
      deleteAccount.mockRejectedValue(
        httpError(503, 'SERVICE_UNAVAILABLE', 'Could not delete the account'))
      const { user } = renderPage()
      await askToDelete(user)
      await user.click(submitButton())
      await inDialog().findByRole('alert')
      await user.click(inDialog().getByRole('button', { name: 'Cancel' }))

      await user.click(pageDeleteButton())

      expect(passwordField()).toHaveValue('')
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('deletes the account with the password, ends the session and says so', async () => {
      const { user, router } = renderPage()
      await askToDelete(user)

      await user.click(submitButton())

      expect(await screen.findByText('Login page: account deleted')).toBeInTheDocument()
      expect(router.state.location.pathname).toBe('/login')
      expect(deleteAccount).toHaveBeenCalledExactlyOnceWith('MyPassword123')
      expect(storage.getAccessToken()).toBeNull()
      expect(storage.getSessionEnded()).toBe(false)
    })

    it('refuses an empty password without sending it', async () => {
      const { user } = renderPage()
      await user.click(pageDeleteButton())

      await user.click(submitButton())

      expect(passwordField()).toHaveAccessibleDescription(expect.stringContaining('Password is required'))
      expect(passwordField()).toHaveFocus()
      expect(deleteAccount).not.toHaveBeenCalled()
    })

    it.each([
      ['a password with a space', 'My Password123', 'Password must not contain spaces'],
      // The rules registration applies: no password it refuses is checked
      ['a short password', 'MyPass1', 'Password must be at least 8 characters'],
      ['a password without an uppercase letter', 'mypassword123',
        'Password must contain at least one uppercase letter'],
      ['a password without a number', 'MyPassword', 'Password must contain at least one number'],
    ])('refuses %s without sending it', async (_, password, message) => {
      const { user } = renderPage()
      await askToDelete(user, password)

      await user.click(submitButton())

      expect(passwordField()).toHaveAccessibleDescription(expect.stringContaining(message))
      expect(passwordField()).toHaveFocus()
      expect(deleteAccount).not.toHaveBeenCalled()
    })

    // Nothing was deleted, so the session stays for another try
    it('keeps the session and marks the field when the password is wrong', async () => {
      deleteAccount.mockRejectedValue(
        httpError(403, 'WRONG_PASSWORD', 'The password is incorrect'))
      const { user, router } = renderPage()
      await askToDelete(user)

      await user.click(submitButton())

      await waitFor(() => expect(passwordField()).toHaveFocus())
      expect(passwordField()).toHaveAttribute('aria-invalid', 'true')
      expect(passwordField()).toHaveAccessibleDescription(
        expect.stringContaining('The password is incorrect'))
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      expect(router.state.location.pathname).toBe('/account')
      expect(storage.getAccessToken()).toBe('access-token')
      expect(submitButton()).toHaveAttribute('aria-disabled', 'false')
      expect(passwordField()).not.toHaveAttribute('readonly')
    })

    it.each([
      ['the server fails', httpError(503, 'SERVICE_UNAVAILABLE', 'Could not delete the account'),
        'Could not delete the account'],
      ['the network fails', new Error('Network Error'), 'Network error'],
    ])('keeps the session and says so in the dialog when %s', async (_, error, message) => {
      deleteAccount.mockRejectedValue(error)
      const { user, router } = renderPage()
      await askToDelete(user)

      await user.click(submitButton())

      expect(await inDialog().findByRole('alert')).toHaveTextContent(message)
      expect(router.state.location.pathname).toBe('/account')
      expect(storage.getAccessToken()).toBe('access-token')
      expect(submitButton()).toHaveAttribute('aria-disabled', 'false')
      expect(passwordField()).not.toHaveAttribute('readonly')
    })

    it('clears an earlier error when trying again', async () => {
      let finish
      deleteAccount
        .mockRejectedValueOnce(httpError(503, 'SERVICE_UNAVAILABLE', 'Could not delete the account'))
        .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      const { user } = renderPage()
      await askToDelete(user)
      await user.click(submitButton())
      await screen.findByRole('alert')

      await user.click(submitButton())

      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      await act(async () => finish())
      expect(await screen.findByText('Login page: account deleted')).toBeInTheDocument()
      expect(deleteAccount).toHaveBeenCalledTimes(2)
    })

    it('marks the dialog busy and ignores repeat submits while deleting', async () => {
      let finish
      deleteAccount.mockImplementation(() => new Promise(resolve => { finish = resolve }))
      const { user } = renderPage()
      await askToDelete(user)
      await user.click(submitButton())

      await user.click(submitButton())

      expect(submitButton()).toHaveTextContent('Deleting...')
      expect(submitButton()).toHaveAttribute('aria-disabled', 'true')
      expect(passwordField()).toHaveAttribute('readonly')
      expect(deleteAccount).toHaveBeenCalledTimes(1)
      await act(async () => finish())
    })
  })
})
