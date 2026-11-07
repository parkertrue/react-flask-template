import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useHealth } from '../useHealth'
import { checkHealth } from '../healthService'
import { queryWrapper } from '@/test/query'

vi.mock('../healthService')

// The poll's state updates happen when the timer fires, so advance the clock
// inside act() for React to apply them before the test looks. TanStack Query
// hands each result to React in a setTimeout(0) set once the fetch settles,
// which fake timers run only on a later millisecond: step one past.
const advance = (ms: number) => act(async () => {
  await vi.advanceTimersByTimeAsync(ms)
  await vi.advanceTimersByTimeAsync(1)
})

describe('useHealth', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('should initialize with checking status', () => {
    vi.mocked(checkHealth).mockImplementation(() => new Promise(() => {}))

    const { result } = renderHook(() => useHealth(), { wrapper: queryWrapper() })

    expect(result.current).toBe('checking')
  })

  it('should fetch health status on mount', async () => {
    vi.mocked(checkHealth).mockResolvedValue({ status: 'ok' })

    const { result } = renderHook(() => useHealth(), { wrapper: queryWrapper() })

    await waitFor(() => {
      expect(result.current).toBe('ok')
    })

    expect(checkHealth).toHaveBeenCalledTimes(1)
  })

  it('should handle health check error', async () => {
    vi.mocked(checkHealth).mockRejectedValue(new Error('Connection failed'))

    const { result } = renderHook(() => useHealth(), { wrapper: queryWrapper() })

    await waitFor(() => {
      expect(result.current).toBe('error')
    })

  })

  it('should poll health status every 30 seconds', async () => {
    vi.useFakeTimers()
    vi.mocked(checkHealth).mockResolvedValue({ status: 'ok' })

    renderHook(() => useHealth(), { wrapper: queryWrapper() })
    await advance(0)
    expect(checkHealth).toHaveBeenCalledTimes(1)

    await advance(30000)
    expect(checkHealth).toHaveBeenCalledTimes(2)

    await advance(30000)
    expect(checkHealth).toHaveBeenCalledTimes(3)
  })

  it('should clear interval on unmount', async () => {
    vi.useFakeTimers()
    vi.mocked(checkHealth).mockResolvedValue({ status: 'ok' })

    const { unmount } = renderHook(() => useHealth(), { wrapper: queryWrapper() })
    await advance(0)
    unmount()

    await advance(90000)

    expect(checkHealth).toHaveBeenCalledTimes(1)
  })

  it('should update status when health check returns different value', async () => {
    vi.useFakeTimers()
    vi.mocked(checkHealth)
      .mockResolvedValueOnce({ status: 'ok' })
      .mockResolvedValueOnce({ status: 'degraded' })

    const { result } = renderHook(() => useHealth(), { wrapper: queryWrapper() })
    await advance(0)
    expect(result.current).toBe('ok')

    await advance(30000)

    expect(result.current).toBe('degraded')
  })

  it('keeps the last status while a later poll is in flight', async () => {
    vi.useFakeTimers()
    vi.mocked(checkHealth)
      .mockResolvedValueOnce({ status: 'ok' })
      .mockReturnValueOnce(new Promise(() => {}))

    const { result } = renderHook(() => useHealth(), { wrapper: queryWrapper() })
    await advance(0)
    await advance(30000)

    expect(checkHealth).toHaveBeenCalledTimes(2)
    expect(result.current).toBe('ok')
  })

  it('should recover when health check succeeds after failure', async () => {
    vi.useFakeTimers()
    vi.mocked(checkHealth)
      .mockRejectedValueOnce(new Error('Failed'))
      .mockResolvedValueOnce({ status: 'ok' })

    const { result } = renderHook(() => useHealth(), { wrapper: queryWrapper() })
    await advance(0)
    expect(result.current).toBe('error')

    await advance(30000)

    expect(result.current).toBe('ok')
  })
})
