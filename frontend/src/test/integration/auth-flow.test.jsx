import { describe, it, expect } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { routes } from '@/routes'
import { TERMS_VERSION } from '@/legal'
import { storage } from '@/auth/storage'
import { account, errorBody } from '../fixtures'
import { renderRoutes, signIn } from '../router'
import { handlers, setupMswServer } from '../server'

// The whole app against the real axios client, with the network faked at the
// HTTP layer. Every endpoint answers its happy path unless a test says not.
const server = setupMswServer(...handlers)

async function fillRegistration(user, email) {
  await user.type(screen.getByLabelText('Email'), email)
  await user.type(screen.getByLabelText('Password'), 'Password123')
  await user.type(screen.getByLabelText('Confirm password'), 'Password123')
  await user.click(screen.getByRole('checkbox', { name: /I accept the Terms/ }))
  await user.click(screen.getByRole('button', { name: 'Register' }))
}

async function fillLogin(user, password = 'Password123') {
  await user.type(screen.getByLabelText('Email'), 'test@example.com')
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Log in' }))
}

describe('Authentication Flow Integration Tests', () => {
  describe('Registration Flow', () => {
    it('registers, with the terms accepted, and moves on to the login page, which confirms it', async () => {
      let body
      server.use(http.post('/api/auth/register', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ message: 'User created' }, { status: 201 })
      }))
      const { user } = renderRoutes(routes, '/register')

      await fillRegistration(user, 'test@example.com')

      expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
      // Filled once the page is in place, so screen readers read it
      await waitFor(() =>
        expect(screen.getByRole('status')).toHaveTextContent('Registration successful'))
      expect(body).toEqual(
        { email: 'test@example.com', password: 'Password123', terms_version: TERMS_VERSION })
    })

    it('ties a taken email to the Email field', async () => {
      server.use(
        http.post('/api/auth/register', () => HttpResponse.json(
          errorBody('EMAIL_ALREADY_REGISTERED', 'Email already registered'),
          { status: 409 }))
      )
      const { user } = renderRoutes(routes, '/register')

      await fillRegistration(user, 'existing@example.com')

      const email = screen.getByLabelText('Email')
      await waitFor(() => expect(email).toHaveFocus())
      expect(email).toHaveAttribute('aria-invalid', 'true')
      expect(email).toHaveAccessibleDescription('Email already registered')
    })
  })

  describe('Login Flow', () => {
    it('logs in, returns to the page that asked, and loads it with the new token', async () => {
      server.use(
        http.get('/api/account', ({ request }) => {
          if (request.headers.get('Authorization') !== 'Bearer access-token') {
            return HttpResponse.json(errorBody('AUTH_MISSING_TOKEN'), { status: 401 })
          }
          return HttpResponse.json(account('test@example.com'))
        })
      )
      const { user } = renderRoutes(routes, '/account')

      await fillLogin(user)

      expect(await screen.findByText(/^Member since/)).toBeInTheDocument()
      expect(screen.getByRole('heading', { level: 1, name: 'Account' })).toBeInTheDocument()
    })

    it('shows the server message on invalid credentials', async () => {
      server.use(
        http.post('/api/auth/login', () => HttpResponse.json(
          errorBody('INVALID_CREDENTIALS', 'Invalid email or password'),
          { status: 401 }))
      )
      const { user } = renderRoutes(routes, '/login')

      await fillLogin(user, 'WrongPassword123')

      expect(await screen.findByRole('alert')).toHaveTextContent(/invalid email or password/i)
    })
  })

  describe('Authentication State', () => {
    it('keeps a stored session across a page load', async () => {
      signIn()

      renderRoutes(routes, '/account')

      expect(await screen.findByText(/^Member since/)).toBeInTheDocument()
    })

    it('sends a visitor without a session to the login page', async () => {
      // No handler is needed: the route guard redirects before any request,
      // and an unexpected request would fail the test
      renderRoutes(routes, '/account')

      expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    })

    it('shows the login page, without a reload, when the session cannot be refreshed', async () => {
      signIn()
      server.use(
        http.get('/api/account', () =>
          HttpResponse.json(errorBody('AUTH_TOKEN_EXPIRED'), { status: 401 })),
        http.post('/api/auth/refresh', () =>
          HttpResponse.json(errorBody('AUTH_TOKEN_REVOKED'), { status: 401 }))
      )

      const { router } = renderRoutes(routes, '/account')

      expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
      expect(storage.getAccessToken()).toBeNull()
      expect(window.location.href).toBe('http://localhost/')
      // Logging in again returns to the page
      expect(router.state.location.state.from.pathname).toBe('/account')
    })
  })
})
