import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { UserEvent } from '@testing-library/user-event'
import { routes } from '@/routes'
import { TERMS_VERSION } from '@/legal'
import { storage } from '@/auth/storage'
import type { FromState } from '@/auth/GuestRoute'
import { account, errorBody, tokens } from '../fixtures'
import { renderRoutes, signIn } from '../router'
import { handlers, setupMswServer } from '../server'

// The whole app against the real axios client, with the network faked at the
// HTTP layer. Every endpoint answers its happy path unless a test says not.
const server = setupMswServer(...handlers)

async function finishRegistration(user: UserEvent) {
  await user.type(screen.getByLabelText('Password'), 'Password123')
  await user.type(screen.getByLabelText('Confirm password'), 'Password123')
  await user.click(screen.getByRole('checkbox', { name: /I accept the Terms/ }))
  await user.click(screen.getByRole('button', { name: 'Create account' }))
}

async function fillLogin(user: UserEvent, password = 'Password123') {
  await user.type(screen.getByLabelText('Email'), 'test@example.com')
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Log in' }))
}

describe('Authentication Flow Integration Tests', () => {
  describe('Registration Flow', () => {
    it('asks for a link, then says to check the inbox', async () => {
      let body
      server.use(http.post('/api/auth/register', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ message: 'Check your inbox' }, { status: 202 })
      }))
      const { user } = renderRoutes(routes, '/register')

      await user.type(screen.getByLabelText(/^Email/), 'test@example.com')
      await user.click(screen.getByRole('button', { name: 'Continue' }))

      expect(await screen.findByRole('heading', { name: 'Check your inbox' })).toHaveFocus()
      expect(body).toEqual({ email: 'test@example.com' })
    })

    it("finishes from the link's page, with the terms accepted, signed in", async () => {
      let body
      server.use(http.post('/api/auth/register/complete', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(tokens('new-access', 'new-csrf'))
      }))
      // With the account page to return to (GuestRoute reads the state), so
      // this shared test needs no example feature page after signing in
      const from: FromState = { from: { pathname: '/account', search: '', hash: '', state: null, key: 'k' } }
      const { user } = renderRoutes(routes, {
        pathname: '/register/complete', hash: '#email=test%40example.com&token=a-token', state: from })

      await finishRegistration(user)

      expect(await screen.findByRole('heading', { name: 'Account' })).toBeInTheDocument()
      expect(body).toEqual({ token: 'a-token', password: 'Password123', terms_version: TERMS_VERSION })
      expect(storage.getAccessToken()).toBe('new-access')
      expect(storage.getEmail()).toBe('test@example.com')
    })

    it('says when the link has expired, and offers to start again', async () => {
      server.use(
        http.post('/api/auth/register/complete', () => HttpResponse.json(
          errorBody('LINK_EXPIRED', 'This link has expired'), { status: 400 }))
      )
      const { user } = renderRoutes(routes, '/register/complete#email=test%40example.com&token=a-token')

      await finishRegistration(user)

      expect(await screen.findByRole('alert')).toHaveTextContent('This link has expired')
      expect(screen.getByRole('link', { name: 'Start again' })).toHaveAttribute('href', '/register')
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
      expect((router.state.location.state as FromState).from?.pathname).toBe('/account')
    })
  })
})
