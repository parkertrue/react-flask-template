import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import { useLocation, type Location } from 'react-router-dom'
import type { UserEvent } from '@testing-library/user-event'
import AccountPage from '../AccountPage'
import type { LoginState } from '../LoginPage'
import ProtectedRoute from '@/auth/ProtectedRoute'
import { storage } from '@/auth/storage'
import {
  getAccount, logoutAllDevices, clearAuthCookies, deleteAccount, exportAccountData, requestEmailChange,
  changePassword, listSessions, endSession,
} from '@/auth/authService'
import { saveJsonFile, slugify } from '@/utils/download'
import type { ErrorCode } from '@/api/errors'
import { account, dataExport, errorBody, httpError, sessions, tokens } from '@/test/fixtures'
import { renderRoutes, signIn } from '@/test/router'
import { APP_NAME } from '@/appInfo'

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
    vi.mocked(requestEmailChange).mockResolvedValue()
    vi.mocked(changePassword).mockResolvedValue(tokens('new-access', 'new-csrf'))
    vi.mocked(listSessions).mockResolvedValue(sessions())
  })

  describe('changing the password', () => {
    const dialog = () => screen.getByRole('dialog', { name: 'Change your password?' })
    const inDialog = () => within(dialog())
    const field = {
      current: () => inDialog().getByLabelText('Current password'),
      next: () => inDialog().getByLabelText('New password'),
      confirm: () => inDialog().getByLabelText('Confirm new password'),
    }
    const saveButton = () => inDialog().getByRole('button', { name: /^(save password|saving\.\.\.)$/i })

    interface Values {
      current?: string
      next?: string
      confirm?: string
    }

    async function askToChange(user: UserEvent, values: Values = {}) {
      const { current = 'my old passphrase', next = 'my brand new passphrase' } = values
      const { confirm = next } = values
      await user.click(screen.getByRole('button', { name: 'Change password' }))
      if (current) await user.type(field.current(), current)
      if (next) await user.type(field.next(), next)
      if (confirm) await user.type(field.confirm(), confirm)
    }

    it("asks in a dialog, with the account's name for password managers, starting on the current password", async () => {
      const { user } = renderPage()

      await user.click(screen.getByRole('button', { name: 'Change password' }))

      expect(dialog()).toHaveAccessibleDescription('Every other device signed in to this account will be logged out.')
      expect(inDialog().getByLabelText('Email')).toHaveValue('user@example.com')
      expect(inDialog().getByLabelText('Email')).toHaveAttribute('autocomplete', 'username')
      expect(field.current()).toHaveFocus()
      expect(field.current()).toHaveAttribute('autocomplete', 'current-password')
      expect(field.next()).toHaveAttribute('autocomplete', 'new-password')
      expect(field.next()).toHaveAccessibleDescription('At least 15 characters. A few words make a good one.')
      expect(changePassword).not.toHaveBeenCalled()
    })

    it('changes it, keeps this browser signed in with the new login, and says so', async () => {
      const { user } = renderPage()
      await askToChange(user)

      await user.click(saveButton())

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(changePassword).toHaveBeenCalledExactlyOnceWith('my old passphrase', 'my brand new passphrase')
      expect(storage.getAccessToken()).toBe('new-access')
      expect(storage.getEmail()).toBe('user@example.com')
      expect(screen.getByText('Your password was changed. Every other device was logged out.'))
        .toHaveAttribute('role', 'status')
    })

    it.each<[string, Values, keyof typeof field, string]>([
      ['an empty current password', { current: '' }, 'current', 'Password is required'],
      ['a short new password', { next: 'too short' }, 'next', 'at least 15 characters'],
      ['a new password holding the address', { next: 'mine is user@example.com' }, 'next',
        "doesn't contain your email address"],
      ['the same password', { next: 'my old passphrase' }, 'next', 'Choose a password different from your current one.'],
      ['new passwords that differ', { confirm: 'a different passphrase' }, 'confirm', 'Passwords do not match'],
    ])('refuses %s without sending it', async (_, values, name, message) => {
      const { user } = renderPage()
      await askToChange(user, values)

      await user.click(saveButton())

      expect(field[name]()).toHaveAttribute('aria-invalid', 'true')
      expect(field[name]()).toHaveAccessibleDescription(expect.stringContaining(message))
      expect(field[name]()).toHaveFocus()
      expect(changePassword).not.toHaveBeenCalled()
    })

    it.each([
      ['a wrong current password', 403, 'WRONG_PASSWORD', 'The password is incorrect', 'current'],
      ['an unchanged password', 422, 'PASSWORD_UNCHANGED', 'Choose a password different from your current one.', 'next'],
      ['a guessable password', 422, 'PASSWORD_GUESSABLE', "Choose a password that doesn't contain your email address", 'next'],
      ['a breached password', 422, 'PASSWORD_BREACHED', 'This password has appeared in a data breach', 'next'],
    ] as const)('marks the field for %s, keeping the dialog and the session', async (_, status, code, message, name) => {
      vi.mocked(changePassword).mockRejectedValue(failure(status, code, message))
      const { user } = renderPage()
      await askToChange(user)

      await user.click(saveButton())

      await waitFor(() => expect(field[name]()).toHaveFocus())
      expect(field[name]()).toHaveAccessibleDescription(expect.stringContaining(message))
      expect(saveButton()).toHaveAttribute('aria-disabled', 'false')
      expect(storage.getAccessToken()).toBe('access-token')
    })

    // ProtectedRoute keeps a visitor away; were the page shown without a
    // session, there would be no account to log back in as
    it('sends nothing without a session', async () => {
      const { user } = renderRoutes([{ path: '/account', element: <AccountPage /> }], '/account')
      await user.click(screen.getByRole('button', { name: 'Change password' }))
      expect(inDialog().getByLabelText('Email')).toHaveValue('')
      await user.type(field.current(), 'my old passphrase')
      await user.type(field.next(), 'my brand new passphrase')
      await user.type(field.confirm(), 'my brand new passphrase')

      await user.click(saveButton())

      expect(changePassword).not.toHaveBeenCalled()
    })

    it('says why in the dialog when the server cannot change it', async () => {
      vi.mocked(changePassword).mockRejectedValue(failure(503, 'SERVICE_UNAVAILABLE', 'Service temporarily unavailable'))
      const { user } = renderPage()
      await askToChange(user)

      await user.click(saveButton())

      expect(await inDialog().findByRole('alert')).toHaveTextContent('Service temporarily unavailable')
    })

    it('changes nothing when the user cancels, and asks afresh next time', async () => {
      const { user } = renderPage()
      await askToChange(user)
      await user.click(inDialog().getByRole('button', { name: 'Cancel' }))

      await user.click(screen.getByRole('button', { name: 'Change password' }))

      expect(field.current()).toHaveValue('')
      expect(changePassword).not.toHaveBeenCalled()
    })

    it('marks the dialog busy and ignores repeat submits while saving', async () => {
      const { promise, resolve: finish } = Promise.withResolvers<ReturnType<typeof tokens>>()
      vi.mocked(changePassword).mockReturnValue(promise)
      const { user } = renderPage()
      await askToChange(user)

      await user.click(saveButton())
      await user.click(saveButton())

      expect(saveButton()).toHaveTextContent('Saving...')
      for (const input of Object.values(field)) {
        expect(input()).toHaveAttribute('readonly')
      }
      expect(changePassword).toHaveBeenCalledTimes(1)
      await act(async () => finish(tokens('new-access', 'new-csrf')))
    })
  })

  describe('the account moved elsewhere', () => {
    it("shows the address the account has now, the navbar's too", async () => {
      vi.mocked(getAccount).mockResolvedValue(account('moved@example.com', '2026-01-15T10:30:00+00:00'))

      renderPage()

      expect(await screen.findByText('moved@example.com')).toBeInTheDocument()
      expect(storage.getEmail()).toBe('moved@example.com')
      expect(storage.getAccessToken()).toBe('access-token')
    })

    it('asks again when the window regains focus', async () => {
      renderPage()
      await screen.findByText(/^Member since/)
      vi.mocked(getAccount).mockResolvedValue(account('moved@example.com', '2026-01-15T10:30:00+00:00'))

      act(() => {
        window.dispatchEvent(new Event('visibilitychange'))
        window.dispatchEvent(new Event('focus'))
      })

      await waitFor(() => expect(storage.getEmail()).toBe('moved@example.com'))
      expect(getAccount).toHaveBeenCalledTimes(2)
    })
  })

  describe('changing the email', () => {
    const dialog = () => screen.getByRole('dialog', { name: 'Change your email?' })
    const inDialog = () => within(dialog())
    const emailField = () => inDialog().getByLabelText('New email')
    const passwordField = () => inDialog().getByLabelText('Password')
    const sendButton = () => inDialog().getByRole('button', { name: /^(send link|sending link\.\.\.)$/i })
    const changeButton = () => screen.getByRole('button', { name: 'Change email' })

    async function askToChange(user: UserEvent, email = 'new@example.com', password = 'my valid passphrase') {
      await user.click(changeButton())
      if (email) await user.type(emailField(), email)
      if (password) await user.type(passwordField(), password)
    }

    it('asks for the new address and the password in a dialog, sending nothing yet', async () => {
      const { user } = renderPage()

      await user.click(changeButton())

      expect(dialog()).toHaveAccessibleDescription(/Nothing changes until you open the link/)
      expect(emailField()).toHaveFocus()
      expect(emailField()).toHaveAttribute('autocomplete', 'email')
      expect(passwordField()).toHaveAttribute('autocomplete', 'current-password')
      expect(requestEmailChange).not.toHaveBeenCalled()
    })

    it('sends the link, closes the dialog and says where it went', async () => {
      const { user } = renderPage()
      await askToChange(user)

      await user.click(sendButton())

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(requestEmailChange).toHaveBeenCalledExactlyOnceWith('new@example.com', 'my valid passphrase')
      expect(screen.getByText(
        'We sent a link to new@example.com. Open it within 24 hours to move your account there.'))
        .toHaveAttribute('role', 'status')
      // Nothing has moved yet
      expect(storage.getEmail()).toBe('user@example.com')
    })

    it.each([
      ['an empty address', '', 'my valid passphrase', 'New email', 'Email is required'],
      ['a malformed address', 'not-an-email', 'my valid passphrase', 'New email', 'Please enter a valid email address'],
      ['an empty password', 'new@example.com', '', 'Password', 'Password is required'],
    ])('refuses %s without sending it', async (_, email, password, label, message) => {
      const { user } = renderPage()
      await askToChange(user, email, password)

      await user.click(sendButton())

      const field = inDialog().getByLabelText(label)
      expect(field).toHaveAttribute('aria-invalid', 'true')
      expect(field).toHaveAccessibleDescription(expect.stringContaining(message))
      expect(field).toHaveFocus()
      expect(requestEmailChange).not.toHaveBeenCalled()
    })

    it.each([
      ['a wrong password', 403, 'WRONG_PASSWORD', 'The password is incorrect', 'Password'],
      ['the current address', 422, 'EMAIL_UNCHANGED', 'This is already your email address', 'New email'],
    ] as const)('marks the field for %s, keeping the dialog', async (_, status, code, message, label) => {
      vi.mocked(requestEmailChange).mockRejectedValue(failure(status, code, message))
      const { user } = renderPage()
      await askToChange(user)

      await user.click(sendButton())

      const field = inDialog().getByLabelText(label)
      await waitFor(() => expect(field).toHaveFocus())
      expect(field).toHaveAccessibleDescription(expect.stringContaining(message))
      expect(sendButton()).toHaveAttribute('aria-disabled', 'false')
    })

    it('says why in the dialog when the server cannot send it', async () => {
      vi.mocked(requestEmailChange).mockRejectedValue(failure(503, 'SERVICE_UNAVAILABLE', 'Service temporarily unavailable'))
      const { user } = renderPage()
      await askToChange(user)

      await user.click(sendButton())

      expect(await inDialog().findByRole('alert')).toHaveTextContent('Service temporarily unavailable')
    })

    it('sends nothing when the user cancels, and asks afresh next time', async () => {
      const { user } = renderPage()
      await askToChange(user)
      await user.click(inDialog().getByRole('button', { name: 'Cancel' }))

      await user.click(changeButton())

      expect(emailField()).toHaveValue('')
      expect(requestEmailChange).not.toHaveBeenCalled()
    })

    it('marks the dialog busy and ignores repeat submits while sending', async () => {
      const { promise, resolve: finish } = Promise.withResolvers<undefined>()
      vi.mocked(requestEmailChange).mockReturnValue(promise)
      const { user } = renderPage()
      await askToChange(user)

      await user.click(sendButton())
      await user.click(sendButton())

      expect(sendButton()).toHaveTextContent('Sending link...')
      expect(emailField()).toHaveAttribute('readonly')
      expect(passwordField()).toHaveAttribute('readonly')
      expect(requestEmailChange).toHaveBeenCalledTimes(1)
      await act(async () => finish(undefined))
    })
  })

  it('lists the devices signed in, and moves focus to "Log out all devices" when the last other one goes', async () => {
    vi.mocked(endSession).mockResolvedValue()
    const { user } = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Log out Firefox on Windows' }))

    await waitFor(() => expect(logoutAll()).toHaveFocus())
    expect(endSession).toHaveBeenCalledExactlyOnceWith('laptop')
  })

  it('shows who is signed in, then loads when they joined', async () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Account' })).toBeInTheDocument()
    expect(screen.getByText('user@example.com')).toBeInTheDocument()
    expect(document.title).toBe(`Account | ${APP_NAME}`)
    expect(details()).toHaveTextContent('Loading account details...')

    // Announced on the same live region that said it was loading
    await waitFor(() => expect(details()).toHaveTextContent(/^Member since /))
    expect(within(details()).getByText(/2026/, { selector: 'time' }))
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
      const filename = `${slugify(APP_NAME)}-data-2026-03-14.json`
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
