import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ApiStatus from '../ApiStatus'
import { checkHealth } from '../healthService'
import { queryWrapper } from '@/test/query'

vi.mock('../healthService')

// The polling itself is tested in useHealth.test.ts. The status is a live
// region, so a screen reader hears it change.
describe('ApiStatus', () => {
  it('shows that it is checking at first', () => {
    vi.mocked(checkHealth).mockReturnValue(new Promise(() => {}))
    render(<ApiStatus />, { wrapper: queryWrapper() })

    expect(screen.getByRole('status')).toHaveTextContent('API status: checking')
  })

  it.each([
    ['the status the API reports', () => vi.mocked(checkHealth).mockResolvedValue({ status: 'ok' }), 'ok'],
    ['an error when the API is unreachable', () => vi.mocked(checkHealth).mockRejectedValue(new Error('Down')), 'error'],
  ])('shows %s', async (_, arrange, status) => {
    arrange()
    render(<ApiStatus />, { wrapper: queryWrapper() })

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(`API status: ${status}`))
  })
})
