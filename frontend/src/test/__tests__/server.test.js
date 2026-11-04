import { describe, it, expect } from 'vitest'
import { api } from '@/api/api'
import { failOnUnhandledRequests, handlers, setupMswServer } from '../server'

const server = setupMswServer(...handlers)

describe('setupMswServer', () => {
  it('fails a test that sends a request no handler matches', async () => {
    const error = await api.get('/nothing-handles-this').catch(e => e)

    // The client only sees a network error, which the app would show
    expect(error.message).toBe('Network Error')
    expect(() => failOnUnhandledRequests(server.unhandled))
      .toThrow('Unhandled request: GET /api/nothing-handles-this')
  })

  it('passes a test whose requests all have handlers', async () => {
    await api.get('/account')

    expect(server.unhandled).toEqual([])
  })
})
