import { afterAll, afterEach, beforeAll } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { account, tokens } from './fixtures'

// The happy path of every shared endpoint; a feature keeps its own handlers
// beside its tests. A test overrides the ones it cares about with
// server.use(); resetHandlers() drops the overrides.
export const handlers = [
  http.get('/api/account', () => HttpResponse.json(account())),
  http.post('/api/auth/register', () =>
    HttpResponse.json({ message: 'User created' }, { status: 201 })),
  http.post('/api/auth/login', () => HttpResponse.json(tokens())),
  http.post('/api/auth/refresh', () => HttpResponse.json(tokens())),
  http.post('/api/auth/logout', () => HttpResponse.json({ message: 'Logged out' })),
  http.post('/api/auth/logout-all', () =>
    HttpResponse.json({ message: 'Logged out from 1 device(s)' })),
  http.post('/api/auth/clear-cookies', () =>
    HttpResponse.json({ message: 'Cookies cleared' })),
]

/**
 * Throws if the test sent a request no handler matched, then forgets them.
 * MSW's 'error' only logs and hands the client a network error, which the
 * app shows as one, so a test with a missing handler could still pass.
 */
export function failOnUnhandledRequests(unhandled) {
  const requests = unhandled.splice(0)
  if (requests.length) {
    throw new Error(`Unhandled request: ${requests.join(', ')}`)
  }
}

/**
 * An MSW server for this test file, started before its tests and reset after
 * each one. A request no handler matches fails the test: an unmocked call is
 * a test bug, never something to skip past.
 */
export function setupMswServer(...initialHandlers) {
  const server = setupServer(...initialHandlers)
  const unhandled = []
  server.events.on('request:unhandled', ({ request }) => {
    unhandled.push(`${request.method} ${new URL(request.url).pathname}`)
  })
  beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
  afterEach(() => {
    server.resetHandlers()
    failOnUnhandledRequests(unhandled)
  })
  afterAll(() => server.close())
  // What a test of this guard checks; other tests leave it to afterEach
  return Object.assign(server, { unhandled })
}
