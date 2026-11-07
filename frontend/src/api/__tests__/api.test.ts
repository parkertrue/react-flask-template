import { describe, it, expect, afterEach, onTestFinished, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { api } from '../api'
import { errorCode, type ErrorCode } from '../errors'
import { storage } from '@/auth/storage'
import { errorBody, tokens } from '@/test/fixtures'
import { setupMswServer } from '@/test/server'

// No default handlers: each test mocks exactly the endpoints it expects
const server = setupMswServer()

afterEach(() => {
  window.location.href = 'http://localhost/'
})

const expired = () => HttpResponse.json(errorBody('AUTH_TOKEN_EXPIRED'), { status: 401 })

// The error code a request failed with, if it failed
const failedWith = (request: Promise<unknown>) => request.then(() => undefined, errorCode)

// A backend that expires every access token except the latest one it issued,
// and, like flask-jwt-extended, requires the CSRF value of the current
// refresh token on refresh.
function mockBackend() {
  const state = { issued: 0, validToken: 'access-0', csrf: 'csrf-0', refreshCalls: [] as (string | null)[] }

  server.use(
    http.post('/api/auth/refresh', ({ request }) => {
      const sent = request.headers.get('X-CSRF-REFRESH-TOKEN')
      state.refreshCalls.push(sent)
      if (sent !== state.csrf) {
        return HttpResponse.json(errorBody('AUTH_MISSING_TOKEN'), { status: 401 })
      }
      state.issued += 1
      state.validToken = `access-${state.issued}`
      state.csrf = `csrf-${state.issued}`
      return HttpResponse.json(tokens(state.validToken, state.csrf))
    }),
    http.get('/api/protected', ({ request }) => {
      if (request.headers.get('Authorization') !== `Bearer ${state.validToken}`) {
        return expired()
      }
      return HttpResponse.json({ ok: true })
    })
  )

  storage.setAccessToken('stale-token')
  storage.setRefreshCsrf('csrf-0')
  return state
}

describe('api client configuration', () => {
  it('uses the /api base URL', () => {
    expect(api.defaults.baseURL).toBe('/api')
  })

  it('fails a request with the storage error when the browser blocks storage', async () => {
    const blocked = new DOMException('Storage is disabled', 'SecurityError')
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw blocked
    })
    onTestFinished(() => getItem.mockRestore())

    // No handler: the request must never go out (the server fails on any)
    await expect(api.get('/account')).rejects.toBe(blocked)
  })
})

describe('request headers', () => {
  function captureHeaders(method: 'get' | 'post', path: string) {
    const captured: { authorization?: string | null; csrf?: string | null } = {}
    server.use(
      http[method](`/api${path}`, ({ request }) => {
        captured.authorization = request.headers.get('Authorization')
        captured.csrf = request.headers.get('X-CSRF-REFRESH-TOKEN')
        return HttpResponse.json({})
      })
    )
    return captured
  }

  it('attaches the stored access token', async () => {
    storage.setAccessToken('abc')
    const captured = captureHeaders('get', '/protected')

    await api.get('/protected')

    expect(captured.authorization).toBe('Bearer abc')
  })

  it('omits Authorization when logged out', async () => {
    const captured = captureHeaders('get', '/protected')

    await api.get('/protected')

    expect(captured.authorization).toBeNull()
  })

  it.each(['/auth/refresh', '/auth/logout', '/auth/logout-all'])(
    'sends the CSRF header to %s',
    async (path) => {
      storage.setRefreshCsrf('csrf-value')
      const captured = captureHeaders('post', path)

      await api.post(path)

      expect(captured.csrf).toBe('csrf-value')
    }
  )

  it('does not send the CSRF header elsewhere', async () => {
    storage.setRefreshCsrf('csrf-value')
    const captured = captureHeaders('post', '/protected')

    await api.post('/protected', { value: 'x' })

    expect(captured.csrf).toBeNull()
  })
})

describe('expired access token', () => {
  it('refreshes, stores the new tokens, and retries the request', async () => {
    const backend = mockBackend()

    const response = await api.get('/protected')

    expect(response.status).toBe(200)
    expect(storage.getAccessToken()).toBe('access-1')
    expect(storage.getRefreshCsrf()).toBe('csrf-1')
    expect(backend.refreshCalls).toEqual(['csrf-0'])
  })

  it('sends the rotated CSRF token on the next refresh', async () => {
    const backend = mockBackend()
    await api.get('/protected')

    storage.setAccessToken('stale-again')
    const response = await api.get('/protected')

    expect(response.status).toBe(200)
    expect(backend.refreshCalls).toEqual(['csrf-0', 'csrf-1'])
  })

  it('shares one refresh between concurrent requests', async () => {
    const backend = mockBackend()

    const responses = await Promise.all([api.get('/protected'), api.get('/protected')])

    expect(responses.map(r => r.status)).toEqual([200, 200])
    expect(backend.refreshCalls).toHaveLength(1)
  })

  it('fails every waiting request when the shared refresh fails', async () => {
    const backend = mockBackend()
    // Hold the refresh until both requests have failed, so the second one is
    // queued behind it rather than starting its own
    let expiredCount = 0
    const { promise: gate, resolve: bothExpired } = Promise.withResolvers<undefined>()
    server.use(
      http.get('/api/protected', () => {
        expiredCount += 1
        if (expiredCount === 2) bothExpired(undefined)
        return expired()
      }),
      http.post('/api/auth/refresh', async () => {
        await gate
        backend.refreshCalls.push('held')
        return HttpResponse.json(errorBody('AUTH_TOKEN_REVOKED'), { status: 401 })
      })
    )

    const results = await Promise.all([failedWith(api.get('/protected')), failedWith(api.get('/protected'))])

    expect(results).toEqual(['AUTH_TOKEN_REVOKED', 'AUTH_TOKEN_REVOKED'])
    expect(backend.refreshCalls).toEqual(['held'])
    expect(storage.getAccessToken()).toBeNull()
  })

  it('refreshes at most once for a request that stays expired', async () => {
    // The refresh succeeds, but the retried request is still rejected (clock
    // skew, a backend bug): it must fail, not refresh again in a loop. Any
    // second refresh is refused, so a loop ends in this test as a wrong
    // answer instead of hanging the run.
    let refreshes = 0
    server.use(
      http.get('/api/protected', () => expired()),
      http.post('/api/auth/refresh', () => {
        refreshes += 1
        return refreshes === 1
          ? HttpResponse.json(tokens('access-1', 'csrf-1'))
          : HttpResponse.json(errorBody('RATE_LIMITED'), { status: 429 })
      })
    )
    storage.setAccessToken('stale-token')

    expect(await failedWith(api.get('/protected'))).toBe('AUTH_TOKEN_EXPIRED')
    expect(refreshes).toBe(1)
  })

  // AuthProvider sees the cleared storage and the route guard sends the user
  // to log in: no page reload
  it('ends the session, without reloading, when the refresh is rejected', async () => {
    mockBackend()
    storage.setRefreshCsrf('wrong')

    await expect(api.get('/protected')).rejects.toMatchObject({ response: { status: 401 } })

    expect(storage.getAccessToken()).toBeNull()
    // So the login page can say why the user is there
    expect(storage.getSessionEnded()).toBe(true)
    expect(window.location.href).toBe('http://localhost/')
  })

  // A session past its 30 days: the refresh carries the stale access token
  // and fails with the same code. Treating that as another expired request
  // would queue the refresh behind itself, and the app would hang for good.
  it('ends the session when the refresh token itself has expired', { timeout: 3000 }, async () => {
    mockBackend()
    server.use(http.post('/api/auth/refresh', expired))

    await expect(api.get('/protected')).rejects.toMatchObject({ response: { status: 401 } })

    expect(storage.getAccessToken()).toBeNull()
  })

  it.each<[string, number, ErrorCode]>([
    ['rate limited', 429, 'RATE_LIMITED'],
    ['unavailable', 503, 'SERVICE_UNAVAILABLE'],
  ])('keeps the session when the refresh is %s', async (_, status, code) => {
    mockBackend()
    server.use(
      http.post('/api/auth/refresh', () =>
        HttpResponse.json(errorBody(code), { status }))
    )

    expect(await failedWith(api.get('/protected'))).toBe(code)
    expect(storage.getAccessToken()).toBe('stale-token')
    expect(storage.getRefreshCsrf()).toBe('csrf-0')
    expect(window.location.href).toBe('http://localhost/')
  })

  it('keeps the session when the refresh cannot reach the server', async () => {
    mockBackend()
    server.use(http.post('/api/auth/refresh', () => HttpResponse.error()))

    await expect(api.get('/protected')).rejects.toMatchObject({ code: 'ERR_NETWORK' })

    expect(storage.getAccessToken()).toBe('stale-token')
    expect(window.location.href).toBe('http://localhost/')
  })

  it('retries the refresh on the next request after a temporary failure', async () => {
    const backend = mockBackend()
    server.use(
      http.post('/api/auth/refresh', () =>
        HttpResponse.json(errorBody('RATE_LIMITED'), { status: 429 }),
      { once: true })
    )
    await api.get('/protected').catch(() => {})

    const response = await api.get('/protected')

    expect(response.status).toBe(200)
    expect(backend.refreshCalls).toEqual(['csrf-0'])
  })
})

describe('refreshing across tabs', () => {
  // jsdom has no Web Locks; stand in for the browser's
  type Request = (name: string, callback: () => unknown) => unknown
  function stubLocks(request: Request) {
    Object.defineProperty(navigator, 'locks', { value: { request }, configurable: true })
  }
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'locks')
  })

  it('refreshes inside the shared lock', async () => {
    const backend = mockBackend()
    const request = vi.fn<Request>((_name, callback) => callback())
    stubLocks(request)

    const response = await api.get('/protected')

    expect(response.status).toBe(200)
    expect(request).toHaveBeenCalledWith('auth-refresh', expect.any(Function))
    expect(backend.refreshCalls).toEqual(['csrf-0'])
  })

  it('uses the token another tab stored while this one waited', async () => {
    const backend = mockBackend()
    // The other tab held the lock, refreshed, and stored its new token
    stubLocks((_name, callback) => {
      storage.setAccessToken(backend.validToken)
      return callback()
    })

    const response = await api.get('/protected')

    expect(response.status).toBe(200)
    expect(backend.refreshCalls).toEqual([])
  })
})

describe('invalid or missing token', () => {
  const rejectWith = (method: 'get' | 'post', path: string, code: ErrorCode) => server.use(
    http[method](`/api${path}`, () =>
      HttpResponse.json(errorBody(code), { status: 401 }))
  )

  it('ends the session, without reloading, on an invalid token', async () => {
    storage.setAccessToken('forged')
    rejectWith('get', '/protected', 'AUTH_INVALID_TOKEN')

    await expect(api.get('/protected')).rejects.toMatchObject({ response: { status: 401 } })

    expect(storage.getAccessToken()).toBeNull()
    expect(storage.getSessionEnded()).toBe(true)
    expect(window.location.href).toBe('http://localhost/')
  })

  it('leaves logout failures to the caller', async () => {
    storage.setAccessToken('token')
    rejectWith('post', '/auth/logout', 'AUTH_MISSING_TOKEN')

    await expect(api.post('/auth/logout')).rejects.toMatchObject({ response: { status: 401 } })

    expect(storage.getAccessToken()).toBe('token')
    expect(storage.getSessionEnded()).toBe(false)
    expect(window.location.href).toBe('http://localhost/')
  })
})
