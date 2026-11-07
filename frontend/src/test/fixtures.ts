import { AxiosError, AxiosHeaders } from 'axios'
import { ERROR_CODES, type ErrorBody, type ErrorCode } from '@/api/errors'
import type { Account, Tokens } from '@/auth/authService'

// API responses as the backend sends them. Build fakes from these rather
// than by hand, so a mocked response cannot drift from the real one.

/**
 * The body of an error response: { error: { code, message } }. The type
 * check refuses a code the backend never sends; this refuses one that
 * arrives untyped too.
 */
export function errorBody(code: ErrorCode, message = 'Request failed'): ErrorBody {
  if (!ERROR_CODES.includes(code)) {
    throw new Error(`The backend never sends the error code ${code}`)
  }
  return { error: { code, message } }
}

/**
 * A request that got this response, as the api client rejects it: an
 * AxiosError carrying the status and body. The body is usually errorBody's.
 */
export function httpError(status: number, data: unknown = {}) {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_RESPONSE, config, null, {
    status, statusText: '', headers: {}, config, data,
  })
}

/** The body of GET /api/account */
export function account(email = 'user@example.com', created_at = '2026-01-15T10:30:00+00:00'): Account {
  return { email, created_at }
}

/** The body of a successful login or refresh */
export function tokens(access_token = 'access-token', refresh_csrf = 'refresh-csrf'): Tokens {
  return { access_token, refresh_csrf }
}
