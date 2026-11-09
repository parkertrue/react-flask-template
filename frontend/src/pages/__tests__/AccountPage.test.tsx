import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import { useLocation, type Location } from 'react-router-dom'
import type { UserEvent } from '@testing-library/user-event'
import AccountPage from '../AccountPage'
import type { LoginState } from '../LoginPage'
import ProtectedRoute from '@/auth/ProtectedRoute'
import { storage } from '@/auth/storage'
import {
  getAccount, logoutAllDevices, clearAuthCookies, deleteAccount, exportAccountData,
} from '@/auth/authService'
import { saveJsonFile } from '@/utils/download'
import type { ErrorCode } from '@/api/errors'
import { account, dataExport, errorBody, httpError } from '@/test/fixtures'
import { renderRoutes, signIn } from '@/test/router'
import { APP_NAME } from '@/appName'

vi.mock('@/auth/authService')
// Only the browser's download is stood in for; the file's name is the page's
vi.mock('@/utils/download', async importOriginal => ({
  ...await importOriginal<typeof import('@/utils/download')>(),
  saveJsonFile: vi.fn(),
}))

// Says whether it was reached from a deleted account, as LoginPage does
function LoginStand() {
  const { state } = useLocation() as Location<LoginState | null>
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

// The page's own, the first in the document: the dialog's confirm button
// shares its name, and jsdom leaves the page behind the dialog reachable
const logoutAll = () => screen.getAllByRole('button', { name: /log out all devices|logging out/i })[0] as HTMLElement
const logoutAllDialog = () => screen.getByRole('dialog', { name: 'Log out all devices?' })

async function confirmLogoutAll(user: UserEvent) {
  await user.click(logoutAll())
  await user.click(within(logoutAllDialog()).getByRole('button', { name: 'Log out all devices' }))
}

// The account details' live region, the first in the document
const details = () => screen.getAllByRole('status')[0] as HTMLElement

// A failed request, with the backend's error body when there is a code
const failure = (status: number, code?: ErrorCode, message?: string) =>
  httpError(status, code ? errorBody(code, message) : {})

describe('AccountPage', () => {
  beforeEach(() => {
    vi.mocked(getAccount).mockResolvedValue(account('user@example.com', '2026-01-15T10:30:00+00:00'))
    vi.mocked(logoutAllDevices).mockResolvedValue()
    vi.mocked(clearAuthCookies).mockResolvedValue()
    vi.mocked(deleteAccount).mockResolvedValue()
    vi.mocked(exportAccountData).mockResolvedValue(dataExport())
  })

  it('shows who is signed in, then loads when they joined', async () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Account' })).toBeInTheDocument()
    expect(screen.getByText('user@example.com')).toBeInTheDocument()
    expect(document.title).toBe(`Account | ${APP_NAME}`)
    expect(details()).toHaveTextContent('Loading account details...')

    // Announced on the same live region that said it was loading
    await waitFor(() => expect(details()).toHaveTextContent(/^Member since /))
    expect(screen.getByText(/2026/, { selector: 'time' }))
      .toHaveAttribute('dateTime', '2026-01-15T10:30:00+00:00')
    expect(getAccount).toHaveBeenCalledTimes(1)
  })

  it('says so when the account cannot be loaded, and still offers logout everywhere', async () => {
    vi.mocked(getAccount).mockRejectedValue(failure(503, 'SERVICE_UNAVAILABLE', 'Service temporarily unavailable'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Service temporarily unavailable')
    expect(details()).toHaveTextContent('')
    expect(logoutAll()).toBeInTheDocument()
  })

  it('asks before logging every device out, signing nothing out yet', async () => {
    const { user } = renderPage()

    await user.click(logoutAll())

    expect(logoutAllDevices).not.toHaveBeenCalled()
    expect(logoutAllDialog()).toHaveAccessibleDescription(/this browser included/)
    // Starts on the answer that changes nothing
    expect(within(logoutAllDialog()).getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('signs nothing out when the user cancels', async () => {
    const { user } = renderPage()
    await user.click(logoutAll())

    await user.click(within(logoutAllDialog()).getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(logoutAll()).toHaveFocus()
    expect(logoutAllDevices).not.toHaveBeenCalled()
    expect(storage.getAccessToken()).toBe('access-token')
  })

  it('signs every device out, ends this session and goes home', async () => {
    const { user, router } = renderPage()

    await confirmLogoutAll(user)

    expect(await screen.findByText('Home page')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/')
    expect(logoutAllDevices).toHaveBeenCalledTimes(1)
    expect(storage.getAccessToken()).toBeNull()
  })

  // Other devices stay signed in unless the server revoked them, so a
  // failure must say so and leave this session for a retry
  it.each([
    ['the server fails', failure(503, 'SERVICE_UNAVAILABLE', 'Could not log out other devices'),
      'Could not log out other devices'],
    ['the network fails', new Error('Network Error'), 'Network error'],
  ])('keeps the session and says so when %s', async (_, error, message) => {
    vi.mocked(logoutAllDevices).mockRejectedValue(error)
    const { user } = renderPage()

    await confirmLogoutAll(user)

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(storage.getAccessToken()).toBe('access-token')
    expect(clearAuthCookies).not.toHaveBeenCalled()
    expect(logoutAll()).toHaveAttribute('aria-disabled', 'false')
  })

  it('ends the session when the server says it is already over (401)', async () => {
    vi.mocked(logoutAllDevices).mockRejectedValue(failure(401))
    const { user, router } = renderPage()

    await confirmLogoutAll(user)

    expect(await screen.findByText('Home page')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/')
    expect(storage.getAccessToken()).toBeNull()
    expect(clearAuthCookies).toHaveBeenCalledTimes(1)
  })

  it('clears an earlier error when trying again', async () => {
    vi.mocked(logoutAllDevices).mockRejectedValueOnce(failure(503, 'SERVICE_UNAVAILABLE'))
    const { user } = renderPage()
    await confirmLogoutAll(user)
    await screen.findByRole('alert')

    await confirmLogoutAll(user)

    expect(await screen.findByText('Home page')).toBeInTheDocument()
    expect(logoutAllDevices).toHaveBeenCalledTimes(2)
  })

  it('keeps focus and ignores repeat clicks while the request is in flight', async () => {
    const { promise, resolve: finish } = Promise.withResolvers<undefined>()
    vi.mocked(logoutAllDevices).mockReturnValue(promise)
    const { user } = renderPage()

    await confirmLogoutAll(user)
    await user.click(logoutAll())

    expect(logoutAll()).toHaveTextContent('Logging out...')
    expect(logoutAll()).toHaveAttribute('aria-disabled', 'true')
    expect(logoutAll()).toHaveFocus()
    // A busy button asks nothing
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(logoutAllDevices).toHaveBeenCalledTimes(1)
    await act(async () => finish(undefined))
  })

  describe('downloading the data', () => {
    const section = () => within(screen.getByRole('region', { name: 'Your data' }))
    const downloadButton = () => section().getByRole('button', { name: /download your data|preparing download/i })

    it('saves the export as a file named after the app and the day, and says so', async () => {
      const { user } = renderPage()

      await user.click(downloadButton())

      // The server's UTC date, whatever the local clock says
      const filename = 'react-flask-template-data-2026-03-14.json'
      expect(await section().findByRole('status')).toHaveTextContent(`Download started: ${filename}`)
      expect(saveJsonFile).toHaveBeenCalledExactlyOnceWith(filename, dataExport())
    })

    it('says why when the export fails, saving nothing', async () => {
      vi.mocked(exportAccountData).mockRejectedValue(failure(429, 'RATE_LIMITED', 'Too many requests'))
      const { user } = renderPage()

      await user.click(downloadButton())

      expect(await section().findByRole('alert')).toHaveTextContent('Too many requests')
      expect(section().getByRole('status')).toHaveTextContent('')
      expect(saveJsonFile).not.toHaveBeenCalled()
      expect(downloadButton()).toHaveTextContent('Download your data')
    })

    it('clears an earlier error when trying again', async () => {
      vi.mocked(exportAccountData).mockRejectedValueOnce(failure(503, 'SERVICE_UNAVAILABLE'))
      const { user } = renderPage()
      await user.click(downloadButton())
      await section().findByRole('alert')

      await user.click(downloadButton())

      await waitFor(() => expect(section().getByRole('status')).toHaveTextContent(/^Download started/))
      expect(section().queryByRole('alert')).not.toBeInTheDocument()
    })

    it('keeps focus and ignores repeat clicks while preparing', async () => {
      const { promise, resolve: finish } = Promise.withResolvers<ReturnType<typeof dataExport>>()
      vi.mocked(exportAccountData).mockReturnValue(promise)
      const { user } = renderPage()

      await user.click(downloadButton())
      await user.click(downloadButton())

      expect(downloadButton()).toHaveTextContent('Preparing download...')
      expect(downloadButton()).toHaveAttribute('aria-disabled', 'true')
      expect(downloadButton()).toHaveFocus()
      expect(exportAccountData).toHaveBeenCalledTimes(1)
      await act(async () => finish(dataExport()))
      expect(downloadButton()).toHaveAttribute('aria-disabled', 'false')
    })
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
    const pageDeleteButton = () => screen.getAllByRole('button', { name: 'Delete account' })[0] as HTMLElement

    async function askToDelete(user: UserEvent, password = 'my valid passphrase') {
      await user.click(pageDeleteButton())
      await user.type(passwordField(), password)
    }

    it('asks for the password in a dialog, deleting nothing yet', async () => {
      const { user } = renderPage()

      await user.click(pageDeleteButton())

      expect(dialog()).toHaveAccessibleDescription(/cannot be undone/)
      expect(passwordField()).toHaveFocus()
      expect(passwordField()).toHaveAccessibleDescription('Enter your password to confirm.')
      // Room for the longest password in emoji, two UTF-16 units each
      expect(passwordField()).toHaveAttribute('maxlength', String(2 * 128))
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
      vi.mocked(deleteAccount).mockRejectedValue(
        failure(503, 'SERVICE_UNAVAILABLE', 'Could not delete the account'))
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
      expect(deleteAccount).toHaveBeenCalledExactlyOnceWith('my valid passphrase')
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
      // The rules registration applies: no password it refuses is checked
      ['a short password', 'too short', 'Password must be at least 15 characters'],
      ['a short password in emoji', '😀'.repeat(14), 'Password must be at least 15 characters'],
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
      vi.mocked(deleteAccount).mockRejectedValue(
        failure(403, 'WRONG_PASSWORD', 'The password is incorrect'))
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
      ['the server fails', failure(503, 'SERVICE_UNAVAILABLE', 'Could not delete the account'),
        'Could not delete the account'],
      ['the network fails', new Error('Network Error'), 'Network error'],
    ])('keeps the session and says so in the dialog when %s', async (_, error, message) => {
      vi.mocked(deleteAccount).mockRejectedValue(error)
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
      const { promise, resolve: finish } = Promise.withResolvers<undefined>()
      vi.mocked(deleteAccount)
        .mockRejectedValueOnce(failure(503, 'SERVICE_UNAVAILABLE', 'Could not delete the account'))
        .mockReturnValueOnce(promise)
      const { user } = renderPage()
      await askToDelete(user)
      await user.click(submitButton())
      await screen.findByRole('alert')

      await user.click(submitButton())

      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      await act(async () => finish(undefined))
      expect(await screen.findByText('Login page: account deleted')).toBeInTheDocument()
      expect(deleteAccount).toHaveBeenCalledTimes(2)
    })

    it('marks the dialog busy and ignores repeat submits while deleting', async () => {
      const { promise, resolve: finish } = Promise.withResolvers<undefined>()
      vi.mocked(deleteAccount).mockReturnValue(promise)
      const { user } = renderPage()
      await askToDelete(user)
      await user.click(submitButton())

      await user.click(submitButton())

      expect(submitButton()).toHaveTextContent('Deleting...')
      expect(submitButton()).toHaveAttribute('aria-disabled', 'true')
      expect(passwordField()).toHaveAttribute('readonly')
      expect(deleteAccount).toHaveBeenCalledTimes(1)
      await act(async () => finish(undefined))
    })
  })
})
