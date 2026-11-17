import { describe, it, expect, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import type { UserEvent } from '@testing-library/user-event'
import CompletePasswordResetPage from '../CompletePasswordResetPage'
import LoginPage from '../LoginPage'
import GuestRoute from '@/auth/GuestRoute'
import { completePasswordReset } from '@/auth/authService'
import { storage } from '@/auth/storage'
import { errorBody, httpError, linkToken } from '@/test/fixtures'
import { renderRoutes, signIn } from '@/test/router'
import { APP_NAME } from '@/appInfo'

vi.mock('@/auth/authService')

const TOKEN = linkToken('user@example.com', 'a1b2c3')
const LINK = `/password-reset/complete#token=${TOKEN}`

function renderPage(entry = LINK) {
  return renderRoutes([
    { path: '/password-reset/complete', element: <CompletePasswordResetPage /> },
    // The real login page, behind its guard, to show where a reset ends
    { element: <GuestRoute />, children: [{ path: '/login', element: <LoginPage /> }] },
  ], entry)
}

const field = {
  password: () => screen.getByLabelText('New password'),
  confirmPassword: () => screen.getByLabelText('Confirm new password'),
}
const emailField = () => screen.getByLabelText('Email')
const submitButton = () => screen.getByRole('button', { name: /save password|saving/i })

interface Values {
  password?: string
  confirmPassword?: string
}

async function fill(user: UserEvent, values: Values = {}) {
  const { password = 'a valid passphrase' } = values
  const { confirmPassword = password } = values
  await user.type(field.password(), password)
  await user.type(field.confirmPassword(), confirmPassword)
}

describe('CompletePasswordResetPage', () => {
  it("shows the token's address, read-only, for password managers, and the new password's fields", () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Choose a new password' })).toBeInTheDocument()
    expect(emailField()).toHaveValue('user@example.com')
    expect(emailField()).toHaveAttribute('readonly')
    expect(emailField()).toHaveAttribute('autocomplete', 'username')
    expect(field.password()).toHaveAttribute('autocomplete', 'new-password')
    expect(field.password()).toHaveAccessibleDescription('At least 15 characters. A few words make a good one.')
    expect(field.password()).toHaveAttribute('maxlength', String(2 * 128))
    expect(field.confirmPassword()).toHaveAttribute('autocomplete', 'new-password')
    expect(document.title).toBe(`Choose a new password | ${APP_NAME}`)
  })

  it('takes the token off the address bar and out of history', async () => {
    const { router } = renderPage()

    await waitFor(() => expect(router.state.location.hash).toBe(''))
    expect(router.state.location.pathname).toBe('/password-reset/complete')
    expect(emailField()).toHaveValue('user@example.com')
  })

  it('shows no address when the token names none, but keeps the form', () => {
    renderPage('/password-reset/complete#token=garbage')

    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
    expect(field.password()).toBeInTheDocument()
  })

  it('says what to do without a link, and offers a new one', () => {
    renderPage('/password-reset/complete')

    expect(screen.getByText(/This page needs the link from your email/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ask for a new link' })).toHaveAttribute('href', '/password-reset')
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  // One example per field: the rules themselves are covered in validation.test.ts
  it.each<[string, Values, keyof typeof field, string]>([
    ['a short password', { password: 'too short' }, 'password', 'at least 15 characters'],
    ['a password holding the address', { password: 'mine is user@example.com' }, 'password',
      "doesn't contain your email address"],
    ['passwords that differ', { confirmPassword: 'a different passphrase' }, 'confirmPassword',
      'Passwords do not match'],
  ])('stops %s, explains, and focuses the bad field', async (_, values, name, message) => {
    const { user } = renderPage()
    await fill(user, values)

    await user.click(submitButton())

    expect(field[name]()).toHaveAttribute('aria-invalid', 'true')
    expect(field[name]()).toHaveAccessibleDescription(expect.stringContaining(message))
    expect(field[name]()).toHaveFocus()
    expect(completePasswordReset).not.toHaveBeenCalled()
  })

  describe('submitting', () => {
    it("sets the password with the link's token, and sends the user to log in with it", async () => {
      vi.mocked(completePasswordReset).mockResolvedValue()
      const { user, router } = renderPage()
      await fill(user)

      await user.click(submitButton())

      expect(await screen.findByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
      // On the status line, once the page has rendered it, and on screen
      await waitFor(() => expect(screen.getByRole('status'))
        .toHaveTextContent('Your password has been changed. Log in with the new one.'))
      expect(screen.getAllByText('Your password has been changed. Log in with the new one.')).toHaveLength(2)
      expect(completePasswordReset).toHaveBeenCalledExactlyOnceWith(TOKEN, 'a valid passphrase')
      // Replaced: Back does not return to a link that no longer works
      expect(router.state.historyAction).toBe('REPLACE')
    })

    it("ends this browser's session, which the reset ended on the server", async () => {
      vi.mocked(completePasswordReset).mockResolvedValue()
      signIn()
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      expect(await screen.findByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
      expect(storage.getAccessToken()).toBeNull()
      // A logout, not a session that ran out
      expect(screen.queryByText(/Your session has ended/)).not.toBeInTheDocument()
    })

    it.each([
      ['an expired link', 'LINK_EXPIRED', 'This link has expired.'],
      ['a link this app never sent', 'LINK_INVALID', 'This link is not valid.'],
      ['a link already used', 'LINK_USED', 'This link has already been used'],
    ] as const)('replaces the form for %s, focuses why, and offers a new link', async (_, code, message) => {
      vi.mocked(completePasswordReset).mockRejectedValue(httpError(400, errorBody(code, 'x')))
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(message)
      expect(alert).toHaveFocus()
      expect(screen.getByRole('link', { name: 'Ask for a new link' })).toHaveAttribute('href', '/password-reset')
      expect(screen.queryByLabelText('New password')).not.toBeInTheDocument()
    })

    // A guessable one reaches the server when the page could not read the
    // token's address
    it.each([
      ['breached', 'PASSWORD_BREACHED', 'This password has appeared in a data breach. Choose another.'],
      ['guessable', 'PASSWORD_GUESSABLE', "Choose a password that doesn't contain your email address or the app's name."],
    ] as const)('ties a %s password to its field, and lets the user try another', async (_, code, message) => {
      vi.mocked(completePasswordReset).mockRejectedValue(httpError(422, errorBody(code, message)))
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      await waitFor(() => expect(field.password()).toHaveFocus())
      expect(field.password()).toHaveAttribute('aria-invalid', 'true')
      expect(field.password()).toHaveAccessibleDescription(expect.stringContaining(message))
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      expect(submitButton()).toHaveAttribute('aria-disabled', 'false')
    })

    it.each([
      ['the service is down', httpError(503, errorBody('SERVICE_UNAVAILABLE', 'Service temporarily unavailable')),
        'Service temporarily unavailable'],
      ['the network fails', new Error('Network Error'), 'Network error'],
    ])('announces why when %s, and lets the user try again', async (_, error, message) => {
      vi.mocked(completePasswordReset).mockRejectedValue(error)
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      expect(await screen.findByRole('alert')).toHaveTextContent(message)
      expect(submitButton()).toHaveAttribute('aria-disabled', 'false')
      expect(field.password()).not.toHaveAttribute('readonly')
    })

    it('keeps focus and ignores repeat submits while the request is in flight', async () => {
      const { promise, resolve: finish } = Promise.withResolvers<undefined>()
      vi.mocked(completePasswordReset).mockReturnValue(promise)
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())
      await user.click(submitButton())

      expect(submitButton()).toHaveTextContent('Saving...')
      expect(submitButton()).toHaveAttribute('aria-disabled', 'true')
      expect(submitButton()).toHaveFocus()
      for (const input of Object.values(field)) {
        expect(input()).toHaveAttribute('readonly')
      }
      expect(completePasswordReset).toHaveBeenCalledTimes(1)
      await act(async () => finish(undefined))
    })
  })
})
