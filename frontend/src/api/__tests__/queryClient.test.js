import { describe, it, expect, vi, afterEach } from 'vitest'
import { focusManager, onlineManager, QueryObserver } from '@tanstack/react-query'
import { createQueryClient } from '../queryClient'

// A query as a page shows it: an observer on a client that listens for focus
// and connectivity, as QueryClientProvider's does
async function showQuery(queryFn) {
  const client = createQueryClient()
  client.mount()
  const observer = new QueryObserver(client, { queryKey: ['x'], queryFn })
  const unsubscribe = observer.subscribe(() => {})
  await vi.waitFor(() => expect(observer.getCurrentResult().fetchStatus).toBe('idle'))
  return { observer, close: () => { unsubscribe(); client.unmount() } }
}

describe('createQueryClient', () => {
  afterEach(() => {
    focusManager.setFocused(undefined)
    onlineManager.setOnline(true)
  })

  it('shows a failed query at once: the api client already refreshes the token', async () => {
    const queryFn = vi.fn().mockRejectedValue(new Error('Service unavailable'))

    const { observer, close } = await showQuery(queryFn)

    expect(observer.getCurrentResult().error.message).toBe('Service unavailable')
    expect(queryFn).toHaveBeenCalledTimes(1)
    close()
  })

  it.each([
    ['the window regains focus', () => {
      focusManager.setFocused(false)
      focusManager.setFocused(true)
    }],
    ['the browser comes back online', () => {
      onlineManager.setOnline(false)
      onlineManager.setOnline(true)
    }],
  ])('does not refetch a shown query when %s', async (_, regain) => {
    const queryFn = vi.fn().mockResolvedValue('data')
    const { close } = await showQuery(queryFn)

    regain()
    await new Promise(resolve => setTimeout(resolve, 10))

    expect(queryFn).toHaveBeenCalledTimes(1)
    close()
  })
})
