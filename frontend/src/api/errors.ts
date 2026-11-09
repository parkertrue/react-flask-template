import { isAxiosError } from 'axios'

// Every error code the backend can send. src/test/__tests__/fixtures.test.ts
// checks this list against backend/app, so a code renamed there fails the
// frontend tests, and comparing a response's code to one not listed here
// fails the type check.
export const ERROR_CODES = [
  'AUTH_INVALID_TOKEN',
  'AUTH_MISSING_TOKEN',
  'AUTH_TOKEN_EXPIRED',
  'AUTH_TOKEN_REVOKED',
  'BAD_REQUEST',
  'EMAIL_ALREADY_REGISTERED',
  'HTTP_ERROR',
  'INTERNAL_ERROR',
  'INVALID_CREDENTIALS',
  'LINK_EXPIRED',
  'LINK_INVALID',
  'METHOD_NOT_ALLOWED',
  'NOT_FOUND',
  'PASSWORD_BREACHED',
  'PAYLOAD_TOO_LARGE',
  'QUOTA_EXCEEDED',
  'RATE_LIMITED',
  'SERVICE_UNAVAILABLE',
  'TERMS_OUTDATED',
  'UNSUPPORTED_MEDIA_TYPE',
  'VALIDATION_ERROR',
  'WRONG_PASSWORD',
] as const

export type ErrorCode = (typeof ERROR_CODES)[number]

// The body of every error response, the backend's and nginx's alike
export interface ErrorBody {
  error: { code: ErrorCode; message: string }
}

// A failed request's response, if it got one. Its body is whatever arrived:
// a proxy in between may answer with something else entirely.
export function errorResponse(err: unknown) {
  return isAxiosError<Partial<ErrorBody> | undefined>(err) ? err.response : undefined
}

// The error code of a failed request's response, if it carried one
export function errorCode(err: unknown): ErrorCode | undefined {
  return errorResponse(err)?.data?.error?.code
}

export function getErrorMessage(err: unknown): string {
  const response = errorResponse(err)
  if (!response) return 'Network error'

  const error = response.data?.error
  if (!error) return 'Unknown error'

  return error.message || 'Request failed'
}
