import { describe, it, expect, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import type { UserEvent } from '@testing-library/user-event'
import CompleteRegistrationPage from '../CompleteRegistrationPage'
import GuestRoute, { AFTER_LOGIN_PATH } from '@/auth/GuestRoute'
import { completeRegistration } from '@/auth/authService'
import { storage } from '@/auth/storage'
import { errorBody, httpError, linkToken, tokens } from '@/test/fixtures'
import { renderRoutes } from '@/test/router'
import { APP_NAME, TERMS_VERSION } from '@/appInfo'

vi.mock('@/auth/authService')

const TOKEN = linkToken('user@example.com')
const LINK = `/signup/complete#token=${TOKEN}`

// The backend's answer: the login, and the account's address
function registered(email = 'user@example.com') {
  return { ...tokens('new-access', 'new-csrf'), email }
}

function renderPage(entry = LINK) {
  return renderRoutes([{
    element: <GuestRoute />,
    children: [{ path: '/signup/complete', element: <CompleteRegistrationPage /> }],
  },
  // Wherever signing in leads, a feature's page the test need not know
  { path: AFTER_LOGIN_PATH, element: <p>Signed in</p> },
  ], entry)
}

const field = {
  password: () => screen.getByLabelText('Password'),
  confirmPassword: () => screen.getByLabelText('Confirm password'),
}
const emailField = () => screen.getByLabelText('Email')
const termsCheckbox = () => screen.getByRole('checkbox', { name: 'I accept the Terms and the Privacy notice' })
const submitButton = () => screen.getByRole('button', { name: /create account|creating account/i })

interface Values {
  password?: string
  confirmPassword?: string
  acceptTerms?: boolean
}

async function fill(user: UserEvent, values: Values = {}) {
  const { password = 'a valid passphrase', acceptTerms = true } = values
  const { confirmPassword = password } = values
  await user.type(field.password(), password)
  await user.type(field.confirmPassword(), confirmPassword)
  if (acceptTerms) await user.click(termsCheckbox())
}

describe('CompleteRegistrationPage', () => {
  it("shows the token's address, read-only, for password managers, and the password fields", () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Finish signing up' })).toBeInTheDocument()
    expect(emailField()).toHaveValue('user@example.com')
    expect(emailField()).toHaveAttribute('readonly')
    expect(emailField()).toHaveAttribute('autocomplete', 'username')
    expect(field.password()).toHaveAttribute('autocomplete', 'new-password')
    expect(field.confirmPassword()).toHaveAttribute('autocomplete', 'new-password')
    expect(document.title).toBe(`Finish signing up | ${APP_NAME}`)
  })

  it('takes the token off the address bar and out of history, keeping the state', async () => {
    const state = { from: { pathname: '/account' } }
    const { router } = renderRoutes([{
      path: '/signup/complete', element: <CompleteRegistrationPage />,
    }], { pathname: '/signup/complete', hash: LINK.slice(LINK.indexOf('#')), state })

    await waitFor(() => expect(router.state.location.hash).toBe(''))
    expect(router.state.location.pathname).toBe('/signup/complete')
    expect(router.state.historyAction).toBe('REPLACE')
    expect(router.state.location.state).toEqual(state)
    // The page still holds what it read
    expect(emailField()).toHaveValue('user@example.com')
  })

  it("shows the address the token names, never one the link adds", () => {
    renderPage(`/signup/complete#email=victim%40example.com&token=${linkToken('attacker@example.com')}`)

    expect(emailField()).toHaveValue('attacker@example.com')
  })

  // Their payloads hold base64url's own characters, '_' and '-'
  it.each(['user?@example.com', 'user~@example.com'])('reads %s from its token', email => {
    renderPage(`/signup/complete#token=${linkToken(email)}`)

    expect(emailField()).toHaveValue(email)
  })

  it.each([
    ['compressed', '.eJyrVkpUslIqLU4tUqoFAB2bBHU.aTime.aSignature'],
    ['not a token', 'garbage'],
  ])('shows no address when the token is %s, but keeps the form', (_, token) => {
    renderPage(`/signup/complete#token=${token}`)

    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
    expect(field.password()).toBeInTheDocument()
  })

  it('asks the user to accept the terms and privacy notice, linked in new tabs', () => {
    renderPage()

    expect(termsCheckbox()).not.toBeChecked()
    expect(screen.getByText('Opens in a new tab.')).not.toBeVisible()
    for (const [name, href] of [['Terms', '/terms'], ['Privacy notice', '/privacy']]) {
      const link = screen.getByRole('link', { name })
      expect(link).toHaveAttribute('href', href)
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAccessibleDescription('Opens in a new tab.')
    }
  })

  it('says what to do without a link, and offers to start again', () => {
    renderPage('/signup/complete')

    expect(screen.getByText(/This page needs the link from your email/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Start again' })).toHaveAttribute('href', '/signup')
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  describe('the password rule', () => {
    const RULE = 'At least 15 characters.'

    it('shows from the start, as the field\'s hint', () => {
      renderPage()

      expect(field.password()).toHaveAccessibleDescription(RULE)
    })

    it('stays beside a message about the password', async () => {
      const { user } = renderPage()
      await fill(user, { password: 'too short' })
      await user.click(submitButton())

      expect(field.password())
        .toHaveAccessibleDescription(`Password must be at least 15 characters ${RULE}`)
    })

    it('lets a password of emoji reach the limit in characters, not UTF-16 units', () => {
      renderPage()

      expect(field.password()).toHaveAttribute('maxlength', String(2 * 128))
    })
  })

  describe('validation', () => {
    // One example per field: the rules themselves are covered in validation.test.ts
    it.each<[string, Values, keyof typeof field | 'acceptTerms', string]>([
      ['a short password', { password: 'too short' }, 'password', 'at least 15 characters'],
      ['a password holding the address', { password: 'mine is user@example.com' }, 'password',
        "doesn't contain your email address"],
      ['passwords that differ', { confirmPassword: 'Different123' }, 'confirmPassword', 'Passwords do not match'],
      ['terms not accepted', { acceptTerms: false }, 'acceptTerms', 'Accept the Terms and the Privacy notice to sign up'],
    ])('stops %s, explains, and focuses the first bad field', async (_, values, name, message) => {
      const { user } = renderPage()
      await fill(user, values)

      await user.click(submitButton())

      const input = name === 'acceptTerms' ? termsCheckbox() : field[name]()
      expect(input).toHaveAttribute('aria-invalid', 'true')
      expect(input).toHaveAccessibleDescription(expect.stringContaining(message))
      expect(input).toHaveFocus()
      expect(completeRegistration).not.toHaveBeenCalled()
    })
  })

  describe('submitting', () => {
    it("makes the account with the link's token, signs in under the server's address and moves on", async () => {
      // Another address than the token's, only to show which one is kept
      vi.mocked(completeRegistration).mockResolvedValue(registered('account@example.com'))
      const { user } = renderPage(`/signup/complete#email=victim%40example.com&token=${TOKEN}`)
      await fill(user)

      await user.click(submitButton())

      expect(await screen.findByText('Signed in')).toBeInTheDocument()
      expect(completeRegistration).toHaveBeenCalledExactlyOnceWith(TOKEN, 'a valid passphrase', TERMS_VERSION)
      expect(storage.getAccessToken()).toBe('new-access')
      expect(storage.getEmail()).toBe('account@example.com')
    })

    it.each([
      ['an expired link', 'LINK_EXPIRED', 'This link has expired.', 'Start again', '/signup'],
      ['a link this app never sent', 'LINK_INVALID', 'This link is not valid.', 'Start again', '/signup'],
      ['a link used for an account since deleted', 'LINK_USED', 'This link has already been used.', 'Start again', '/signup'],
      ['a link already used', 'EMAIL_ALREADY_REGISTERED', 'This account is already set up.', 'Log in', '/login'],
    ] as const)('replaces the form for %s, focuses why, and offers what next', async (_, code, message, action, href) => {
      vi.mocked(completeRegistration).mockRejectedValue(httpError(400, errorBody(code, 'x')))
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(message)
      expect(alert).toHaveFocus()
      expect(screen.getByRole('link', { name: action })).toHaveAttribute('href', href)
      expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    })

    // The field's own message, focused, like a failed submit's. A guessable
    // one reaches the server when the page could not read the token's address.
    it.each([
      ['breached', 'PASSWORD_BREACHED', 'This password has appeared in a data breach. Choose another.'],
      ['guessable', 'PASSWORD_GUESSABLE', "Choose a password that doesn't contain your email address or the app's name."],
    ] as const)('ties a %s password to the Password field, and lets the user try another', async (_, code, message) => {
      vi.mocked(completeRegistration).mockRejectedValue(httpError(422, errorBody(code, message)))
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
      ['the terms have changed', httpError(409, errorBody('TERMS_OUTDATED', 'The terms have changed')),
        'The terms have changed'],
      ['the network fails', new Error('Network Error'), 'Network error'],
    ])('announces why when %s, and lets the user try again', async (_, error, message) => {
      vi.mocked(completeRegistration).mockRejectedValue(error)
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      expect(await screen.findByRole('alert')).toHaveTextContent(message)
      expect(submitButton()).toHaveAttribute('aria-disabled', 'false')
      expect(field.password()).not.toHaveAttribute('readonly')
    })

    it('keeps focus and ignores repeat submits while the request is in flight', async () => {
      const { promise, resolve: finish } = Promise.withResolvers<ReturnType<typeof registered>>()
      vi.mocked(completeRegistration).mockReturnValue(promise)
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())
      await user.click(submitButton())

      expect(submitButton()).toHaveTextContent('Creating account...')
      expect(submitButton()).toHaveAttribute('aria-disabled', 'true')
      expect(submitButton()).toHaveFocus()
      for (const input of Object.values(field)) {
        expect(input()).toHaveAttribute('readonly')
      }
      expect(termsCheckbox()).toHaveAttribute('aria-readonly', 'true')
      await user.click(termsCheckbox())
      expect(termsCheckbox()).toBeChecked()
      expect(completeRegistration).toHaveBeenCalledTimes(1)
      await act(async () => finish(registered()))
    })
  })
})
