import { describe, it, expect, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import LoginPage from '../LoginPage'
import GuestRoute, { AFTER_LOGIN_PATH } from '@/auth/GuestRoute'
import { storage } from '@/auth/storage'
import { loginUser } from '@/auth/authService'
import { errorBody, tokens } from '@/test/fixtures'
import { renderRoutes } from '@/test/router'
import { APP_NAME } from '@/appName'

vi.mock('@/auth/authService')

function renderPage(entry = '/login') {
  return renderRoutes([
    { element: <GuestRoute />, children: [{ path: '/login', element: <LoginPage /> }] },
    { path: AFTER_LOGIN_PATH, element: <p>After-login page</p> },
  ], entry)
}

const field = {
  email: () => screen.getByLabelText('Email'),
  password: () => screen.getByLabelText('Password'),
}
const submitButton = () => screen.getByRole('button', { name: /^log in$|logging in/i })

async function fill(user, { email = 'user@example.com', password = 'Password123' } = {}) {
  if (email) await user.type(field.email(), email)
  if (password) await user.type(field.password(), password)
}

const failure = (status, code, message) => Object.assign(new Error(String(status)), {
  response: { status, data: errorBody(code, message) },
})

describe('LoginPage', () => {
  it('shows the form, with a way to register', () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
    expect(screen.getByRole('form', { name: 'Log in' })).toBeInTheDocument()
    expect(field.email()).toHaveAttribute('autocomplete', 'email')
    expect(field.password()).toHaveAttribute('autocomplete', 'current-password')
    expect(screen.getByRole('link', { name: 'Register' })).toHaveAttribute('href', '/register')
    expect(document.title).toBe(`Log in | ${APP_NAME}`)
  })

  // The status line is in the page from the start, and filled once it is
  // shown: a live region added along with its text is not read
  it('keeps an empty status line for a visitor with nothing to be told', () => {
    renderPage()

    expect(screen.getByRole('status')).toHaveTextContent(/^$/)
  })

  it.each([
    ['a registration that just happened', () => {}, { registered: true },
      'Registration successful. Please log in.'],
    ['a session that ended on its own', () => storage.endSession(), undefined,
      'Your session has ended. Please log in again.'],
    ['a registration over an ended session', () => storage.endSession(), { registered: true },
      'Registration successful. Please log in.'],
    ['an account just deleted', () => {}, { accountDeleted: true },
      'Your account has been deleted.'],
  ])('tells the user about %s', async (_, arrange, state, message) => {
    arrange()
    renderPage({ pathname: '/login', state })

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(message))
    // And on screen, for everyone
    expect(screen.getAllByText(message)).toHaveLength(2)
  })

  describe('validation', () => {
    it.each([
      ['a malformed email', { email: 'not-an-email' }, 'email', 'Please enter a valid email address'],
      ['an empty password', { password: '' }, 'password', 'Password is required'],
      // Every rule registration applies, so no password it refuses is checked
      ['a short password', { password: 'Pass123' }, 'password',
        'Password must be at least 8 characters'],
      ['a password without an uppercase letter', { password: 'password123' }, 'password',
        'Password must contain at least one uppercase letter'],
      ['a password without a lowercase letter', { password: 'PASSWORD123' }, 'password',
        'Password must contain at least one lowercase letter'],
      ['a password without a number', { password: 'Password' }, 'password',
        'Password must contain at least one number'],
      ['a password with a space', { password: 'Pass word123' }, 'password',
        'Password must not contain spaces'],
      ['a password with an emoji', { password: 'Password123😀' }, 'password',
        'Password must not contain emoji or other symbols like © or °'],
      ['an email with non-ASCII before the @', { email: 'josé@example.com' }, 'email',
        'Before the @, an email can use only English letters, numbers and symbols like . _ + -'],
    ])('stops %s, explains, and focuses the field', async (_, values, name, message) => {
      const { user } = renderPage()
      await fill(user, values)

      await user.click(submitButton())

      expect(field[name]()).toHaveAttribute('aria-invalid', 'true')
      expect(field[name]()).toHaveAccessibleDescription(message)
      expect(field[name]()).toHaveFocus()
      expect(loginUser).not.toHaveBeenCalled()
    })

    it('clears a field\'s message once it is edited', async () => {
      const { user } = renderPage()
      await fill(user, { email: 'bad' })
      await user.click(submitButton())

      await user.type(field.email(), 'x')

      expect(field.email()).toHaveAttribute('aria-invalid', 'false')
    })
  })

  describe('submitting', () => {
    it('stores the issued session and moves on to the after-login page', async () => {
      loginUser.mockResolvedValue(tokens('access', 'csrf'))
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      expect(await screen.findByText('After-login page')).toBeInTheDocument()
      expect(loginUser).toHaveBeenCalledWith('user@example.com', 'Password123')
      expect(storage.getAccessToken()).toBe('access')
      expect(storage.getRefreshCsrf()).toBe('csrf')
      expect(storage.getEmail()).toBe('user@example.com')
    })

    it.each([
      ['the credentials are wrong',
        failure(401, 'INVALID_CREDENTIALS', 'Invalid email or password'), 'Invalid email or password'],
      ['the network fails', new Error('Network Error'), 'Network error'],
    ])('announces why when %s, and lets the user try again', async (_, error, message) => {
      loginUser.mockRejectedValue(error)
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      expect(await screen.findByRole('alert')).toHaveTextContent(message)
      expect(storage.getAccessToken()).toBeNull()
      expect(submitButton()).toHaveAttribute('aria-disabled', 'false')
    })

    it('keeps focus and ignores repeat submits while the request is in flight', async () => {
      let finish
      loginUser.mockImplementation(() => new Promise(resolve => { finish = resolve }))
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())
      await user.click(submitButton())

      expect(submitButton()).toHaveTextContent('Logging in...')
      expect(submitButton()).toHaveAttribute('aria-disabled', 'true')
      expect(submitButton()).toHaveFocus()
      expect(field.email()).toHaveAttribute('readonly')
      expect(loginUser).toHaveBeenCalledTimes(1)
      await act(async () => finish(tokens()))
    })
  })
})
