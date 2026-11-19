import { describe, it, expect, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import SessionList from '../SessionList'
import { endSession, listSessions } from '@/auth/authService'
import { errorBody, httpError, sessions } from '@/test/fixtures'
import { renderRoutes, signIn } from '@/test/router'

vi.mock('@/auth/authService')

const fallbackFocus = vi.fn<() => void>()

function renderList() {
  signIn('user@example.com')
  return renderRoutes([{ path: '/account', element: <SessionList fallbackFocus={fallbackFocus} /> }], '/account')
}

// Three devices: two others, then this browser
function threeDevices() {
  const { sessions: [laptop, here] } = sessions()
  if (!laptop || !here) throw new Error('fixtures changed')
  return {
    sessions: [
      laptop,
      { ...laptop, id: 'phone', device: 'Mobile Safari on iOS' },
      here,
    ],
  }
}

const list = () => screen.getByRole('list', { name: 'Signed-in devices' })
const items = () => within(list()).getAllByRole('listitem')
const logOut = (device: string) => screen.getByRole('button', { name: `Log out ${device}` })
const status = () => screen.getByRole('status')

describe('SessionList', () => {
  it('lists each device with when it signed in and was last active, marking this one', async () => {
    vi.mocked(listSessions).mockResolvedValue(sessions())
    renderList()

    await screen.findByRole('list', { name: 'Signed-in devices' })
    const [laptop, here] = items()
    expect(laptop).toHaveTextContent(/^Firefox on Windows/)
    expect(within(laptop as HTMLElement).getAllByText((_, element) => element?.tagName === 'TIME')
      .map(time => time.getAttribute('datetime')))
      .toEqual(['2026-01-10T09:00:00+00:00', '2026-01-15T11:00:00+00:00'])
    expect(here).toHaveTextContent(/^Edge on macOS \(this device\)/)
    // Every device but this one can be logged out from here
    expect(within(laptop as HTMLElement).getByRole('button')).toHaveAccessibleName('Log out Firefox on Windows')
    expect(within(here as HTMLElement).queryByRole('button')).not.toBeInTheDocument()
  })

  it('says it is loading, then why it could not', async () => {
    vi.mocked(listSessions).mockRejectedValue(httpError(503, errorBody('SERVICE_UNAVAILABLE', 'Service temporarily unavailable')))
    renderList()

    expect(screen.getByText('Loading sessions...')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('Service temporarily unavailable')
    expect(screen.queryByText('Loading sessions...')).not.toBeInTheDocument()
  })

  it('logs a device out, drops it, says so and focuses the next device', async () => {
    vi.mocked(listSessions).mockResolvedValue(threeDevices())
    vi.mocked(endSession).mockResolvedValue()
    const { user } = renderList()
    await screen.findByRole('list', { name: 'Signed-in devices' })

    await user.click(logOut('Firefox on Windows'))

    await waitFor(() => expect(status()).toHaveTextContent('Logged out Firefox on Windows.'))
    expect(endSession).toHaveBeenCalledExactlyOnceWith('laptop')
    expect(items().map(item => item.textContent)).toEqual([
      expect.stringMatching(/^Mobile Safari on iOS/), expect.stringMatching(/^Edge on macOS/)])
    expect(logOut('Mobile Safari on iOS')).toHaveFocus()
  })

  it('focuses the previous device when the last one goes', async () => {
    vi.mocked(listSessions).mockResolvedValue(threeDevices())
    vi.mocked(endSession).mockResolvedValue()
    const { user } = renderList()
    await screen.findByRole('list', { name: 'Signed-in devices' })

    await user.click(logOut('Mobile Safari on iOS'))

    await waitFor(() => expect(logOut('Firefox on Windows')).toHaveFocus())
  })

  it('hands focus back to the page when no other device is left', async () => {
    vi.mocked(listSessions).mockResolvedValue(sessions())
    vi.mocked(endSession).mockResolvedValue()
    const { user } = renderList()
    await screen.findByRole('list', { name: 'Signed-in devices' })

    await user.click(logOut('Firefox on Windows'))

    await waitFor(() => expect(fallbackFocus).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('drops a device that had already logged out, and says so', async () => {
    vi.mocked(listSessions).mockResolvedValue(sessions())
    vi.mocked(endSession).mockRejectedValue(httpError(404, errorBody('NOT_FOUND', 'Not found')))
    const { user } = renderList()
    await screen.findByRole('list', { name: 'Signed-in devices' })

    await user.click(logOut('Firefox on Windows'))

    await waitFor(() => expect(status()).toHaveTextContent('Firefox on Windows was already logged out.'))
    expect(items()).toHaveLength(1)
  })

  it('keeps the device and says why when logging it out fails', async () => {
    vi.mocked(listSessions).mockResolvedValue(sessions())
    vi.mocked(endSession).mockRejectedValue(
      httpError(503, errorBody('SERVICE_UNAVAILABLE', 'Could not log out that device, please try again shortly')))
    const { user } = renderList()
    await screen.findByRole('list', { name: 'Signed-in devices' })

    await user.click(logOut('Firefox on Windows'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not log out that device')
    expect(items()).toHaveLength(2)
    expect(logOut('Firefox on Windows')).toHaveAttribute('aria-disabled', 'false')
  })

  it('marks the buttons busy and ignores another click while one device logs out', async () => {
    vi.mocked(listSessions).mockResolvedValue(threeDevices())
    const { promise, resolve: finish } = Promise.withResolvers<undefined>()
    vi.mocked(endSession).mockReturnValue(promise)
    const { user } = renderList()
    await screen.findByRole('list', { name: 'Signed-in devices' })

    await user.click(logOut('Firefox on Windows'))
    await user.click(logOut('Mobile Safari on iOS'))

    const busy = screen.getByRole('button', { name: 'Logging out Firefox on Windows' })
    expect(busy).toHaveTextContent('Logging out...')
    expect(busy).toHaveAttribute('aria-disabled', 'true')
    expect(logOut('Mobile Safari on iOS')).toHaveAttribute('aria-disabled', 'true')
    expect(endSession).toHaveBeenCalledTimes(1)
    await act(async () => finish(undefined))
  })
})
