import { describe, it, expect } from 'vitest'
import { errorCode, errorResponse, getErrorMessage } from '../errors'
import { errorBody, httpError } from '@/test/fixtures'

describe('getErrorMessage', () => {
  it.each([
    ['a request that got no response', new Error('Network Error')],
    ['something other than a failed request', { response: { data: errorBody('BAD_REQUEST', 'Bad') } }],
  ])('should return network error for %s', (_, err) => {
    expect(getErrorMessage(err)).toBe('Network error')
  })

  it('should return error message from response', () => {
    expect(getErrorMessage(httpError(401, errorBody('INVALID_CREDENTIALS', 'Invalid credentials'))))
      .toBe('Invalid credentials')
  })

  it.each([
    ['no error object in the body', {}],
    ['no body at all', undefined],
    // A proxy in between answering with its own page
    ['a body that is not JSON', '<html>Bad gateway</html>'],
  ])('should return the default message for %s', (_, data) => {
    expect(getErrorMessage(httpError(502, data))).toBe('Unknown error')
  })

  it('should return default message when error has no message', () => {
    expect(getErrorMessage(httpError(400, errorBody('BAD_REQUEST', '')))).toBe('Request failed')
  })
})

describe('errorResponse and errorCode', () => {
  it('read the response of a failed request', () => {
    const err = httpError(409, errorBody('QUOTA_EXCEEDED', 'Too many'))

    expect(errorResponse(err)?.status).toBe(409)
    expect(errorCode(err)).toBe('QUOTA_EXCEEDED')
  })

  it('find nothing in an error without a response', () => {
    const err = new Error('Network Error')

    expect(errorResponse(err)).toBeUndefined()
    expect(errorCode(err)).toBeUndefined()
  })
})
