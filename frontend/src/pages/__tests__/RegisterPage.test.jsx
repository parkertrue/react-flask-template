import { describe, it, expect, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import RegisterPage from '../RegisterPage'
import LoginPage from '../LoginPage'
import { registerUser } from '@/auth/authService'
import { errorBody } from '@/test/fixtures'
import { renderRoutes } from '@/test/router'
import { APP_NAME } from '@/appName'
import { TERMS_VERSION } from '@/legal'

vi.mock('@/auth/authService')

function renderPage() {
  return renderRoutes([
    { path: '/register', element: <RegisterPage /> },
    { path: '/login', element: <LoginPage /> },
  ], '/register')
}

const field = {
  email: () => screen.getByLabelText('Email'),
  password: () => screen.getByLabelText('Password'),
  confirmPassword: () => screen.getByLabelText('Confirm password'),
}
const termsCheckbox = () => screen.getByRole('checkbox', { name: 'I accept the Terms and the Privacy notice' })
const submitButton = () => screen.getByRole('button', { name: /register|creating account/i })

async function fill(user, values = {}) {
  const { email = 'user@example.com', password = 'Password123', acceptTerms = true } = values
  const { confirmPassword = password } = values
  for (const [name, value] of Object.entries({ email, password, confirmPassword })) {
    if (value) await user.type(field[name](), value)
  }
  if (acceptTerms) await user.click(termsCheckbox())
}

describe('RegisterPage', () => {
  it('shows the form, without the password rules yet, and a way to log in', () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Register' })).toBeInTheDocument()
    expect(field.email()).toHaveAttribute('autocomplete', 'email')
    expect(field.password()).toHaveAttribute('autocomplete', 'new-password')
    expect(field.confirmPassword()).toHaveAttribute('autocomplete', 'new-password')
    expect(field.password()).toHaveAccessibleDescription('')
    expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
    expect(document.title).toBe(`Register | ${APP_NAME}`)
  })

  it('asks the user to accept the terms and privacy notice, linked in new tabs', () => {
    renderPage()

    expect(termsCheckbox()).not.toBeChecked()
    expect(termsCheckbox()).toHaveAccessibleDescription('Both open in a new tab.')
    for (const [name, href] of [['Terms', '/terms'], ['Privacy notice', '/privacy']]) {
      const link = screen.getByRole('link', { name })
      expect(link).toHaveAttribute('href', href)
      expect(link).toHaveAttribute('target', '_blank')
    }
  })

  describe('the password rules', () => {
    const RULES = 'At least 8 characters, with an uppercase letter, a lowercase letter and a number.'

    it('show with the first password message, and stay once it is fixed', async () => {
      const { user } = renderPage()
      await fill(user, { password: 'password' })
      await user.click(submitButton())

      expect(field.password())
        .toHaveAccessibleDescription(`Password must contain at least one uppercase letter ${RULES}`)

      await user.type(field.password(), 'A')

      expect(field.password()).toHaveAccessibleDescription(RULES)
    })

    it('stay hidden when only another field is wrong', async () => {
      const { user } = renderPage()
      await fill(user, { email: 'not-an-email' })
      await user.click(submitButton())

      expect(field.email()).toHaveAttribute('aria-invalid', 'true')
      expect(field.password()).toHaveAccessibleDescription('')
    })
  })

  describe('validation', () => {
    // One example per field: the rules themselves are covered in validation.test.js
    it.each([
      ['an empty form', { email: '', password: '' }, 'email', 'Email is required'],
      ['a malformed email', { email: 'not-an-email' }, 'email', 'Please enter a valid email address'],
      ['a weak password', { password: 'password' }, 'password', 'uppercase'],
      ['passwords that differ', { confirmPassword: 'Different123' }, 'confirmPassword', 'Passwords do not match'],
      ['terms not accepted', { acceptTerms: false }, 'acceptTerms', 'Accept the Terms and the Privacy notice to register'],
    ])('stops %s, explains, and focuses the first bad field', async (_, values, name, message) => {
      const { user } = renderPage()
      await fill(user, values)

      await user.click(submitButton())

      const input = name === 'acceptTerms' ? termsCheckbox() : field[name]()
      expect(input).toHaveAttribute('aria-invalid', 'true')
      expect(input).toHaveAccessibleDescription(expect.stringContaining(message))
      expect(input).toHaveFocus()
      expect(registerUser).not.toHaveBeenCalled()
    })

    it('clears a field\'s message once it is edited', async () => {
      const { user } = renderPage()
      await fill(user, { confirmPassword: 'Different123' })
      await user.click(submitButton())

      await user.type(field.confirmPassword(), 'x')

      expect(field.confirmPassword()).toHaveAttribute('aria-invalid', 'false')
    })
  })

  describe('submitting', () => {
    it('registers and goes straight to the login page, which confirms it', async () => {
      registerUser.mockResolvedValue({ message: 'User created' })
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
      // The login page fills its status line after its first render
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Registration successful'))
      expect(registerUser).toHaveBeenCalledWith('user@example.com', 'Password123', TERMS_VERSION)
    })

    // The field's own message, focused, like a failed submit's
    it('ties a taken email to the Email field, and lets the user try again', async () => {
      registerUser.mockRejectedValue(Object.assign(new Error('409'), {
        response: { status: 409, data: errorBody('EMAIL_ALREADY_REGISTERED', 'Email already registered') },
      }))
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      await waitFor(() => expect(field.email()).toHaveFocus())
      expect(field.email()).toHaveAttribute('aria-invalid', 'true')
      expect(field.email()).toHaveAccessibleDescription('Email already registered')
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      expect(submitButton()).toHaveAttribute('aria-disabled', 'false')
      expect(field.email()).not.toHaveAttribute('readonly')
    })

    it.each([
      ['the terms have changed', Object.assign(new Error('409'), {
        response: { status: 409, data: errorBody('TERMS_OUTDATED', 'The terms have changed') },
      }), 'The terms have changed'],
      ['the network fails', new Error('Network Error'), 'Network error'],
    ])('announces why when %s, and lets the user try again', async (_, error, message) => {
      registerUser.mockRejectedValue(error)
      const { user } = renderPage()
      await fill(user)

      await user.click(submitButton())

      expect(await screen.findByRole('alert')).toHaveTextContent(message)
      expect(submitButton()).toHaveAttribute('aria-disabled', 'false')
      expect(field.email()).not.toHaveAttribute('readonly')
    })

    it('keeps focus and ignores repeat submits while the request is in flight', async () => {
      let finish
      registerUser.mockImplementation(() => new Promise(resolve => { finish = resolve }))
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
      expect(registerUser).toHaveBeenCalledTimes(1)
      await act(async () => finish({}))
    })
  })
})
