import { describe, it, expect, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import UndoEmailChangePage from '../UndoEmailChangePage'
import { undoEmailChange } from '@/auth/authService'
import { storage } from '@/auth/storage'
import { errorBody, httpError, linkToken } from '@/test/fixtures'
import { renderRoutes, signIn } from '@/test/router'
import { APP_NAME } from '@/appInfo'

vi.mock('@/auth/authService')

const TOKEN = linkToken('old@example.com', '7:1767225600')
const LINK = `/account/email/undo#token=${TOKEN}`

function renderPage(entry = LINK) {
  return renderRoutes([{ path: '/account/email/undo', element: <UndoEmailChangePage /> }], entry)
}

const undoButton = () => screen.getByRole('button', { name: /move my account back|moving it back/i })

describe('UndoEmailChangePage', () => {
  it("asks before moving the account back to the token's address, saying what else happens", () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Undo an email change' })).toBeInTheDocument()
    expect(screen.getByText(/Move your account back to/)).toHaveTextContent(
      'Move your account back to old@example.com? Every device signed in to it will be logged out.')
    expect(document.title).toBe(`Undo an email change | ${APP_NAME}`)
    expect(undoEmailChange).not.toHaveBeenCalled()
  })

  it('takes the token off the address bar and out of history', async () => {
    const { router } = renderPage()

    await waitFor(() => expect(router.state.location.hash).toBe(''))
    expect(undoButton()).toBeInTheDocument()
  })

  it('asks without an address when the token names none', () => {
    renderPage('/account/email/undo#token=garbage')

    expect(screen.getByText(/the address this link was sent to\?/)).toBeInTheDocument()
  })

  it('says what to do without a link', () => {
    renderPage('/account/email/undo')

    expect(screen.getByText(/This page needs the link from the email/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Contact us' })).toHaveAttribute('href', '/contact')
  })

  it('moves the account back and sends the owner to reset the password', async () => {
    vi.mocked(undoEmailChange).mockResolvedValue({ email: 'old@example.com' })
    const { user } = renderPage()

    await user.click(undoButton())

    const done = await screen.findByText(/Your account is back at/)
    expect(done).toHaveTextContent(
      'Your account is back at old@example.com, every device was logged out, and the password no longer works. '
      + 'Reset your password to log in again.')
    expect(done).toHaveFocus()
    expect(undoEmailChange).toHaveBeenCalledExactlyOnceWith(TOKEN)
    expect(screen.getByRole('link', { name: 'Reset your password' })).toHaveAttribute('href', '/password-reset')
  })

  it("ends this browser's session, which the undo ended on the server", async () => {
    vi.mocked(undoEmailChange).mockResolvedValue({ email: 'old@example.com' })
    signIn('new@example.com')
    const { user } = renderPage()

    await user.click(undoButton())

    await screen.findByText(/Your account is back at/)
    expect(storage.getAccessToken()).toBeNull()
  })

  it.each([
    ['an expired link', 'LINK_EXPIRED', 'This link has expired.', 'Contact us', '/contact'],
    ['a link this app never sent', 'LINK_INVALID', 'This link is not valid.', 'Contact us', '/contact'],
    ['an account already back', 'LINK_USED', 'Your account is already at this address.', 'Log in', '/login'],
    ['an old address taken since', 'EMAIL_ALREADY_REGISTERED', 'Another account has this address now', 'Contact us', '/contact'],
  ] as const)('replaces the button for %s, focuses why and offers what next', async (_, code, message, action, href) => {
    vi.mocked(undoEmailChange).mockRejectedValue(httpError(400, errorBody(code, 'x')))
    const { user } = renderPage()

    await user.click(undoButton())

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(message)
    expect(alert).toHaveFocus()
    expect(screen.getByRole('link', { name: action })).toHaveAttribute('href', href)
  })

  it('announces why when the request fails otherwise, and lets the user try again', async () => {
    vi.mocked(undoEmailChange).mockRejectedValue(httpError(503, errorBody('SERVICE_UNAVAILABLE', 'Service temporarily unavailable')))
    const { user } = renderPage()

    await user.click(undoButton())

    expect(await screen.findByRole('alert')).toHaveTextContent('Service temporarily unavailable')
    expect(undoButton()).toHaveAttribute('aria-disabled', 'false')
  })

  it('ignores repeat clicks while the request is in flight', async () => {
    const { promise, resolve: finish } = Promise.withResolvers<{ email: string }>()
    vi.mocked(undoEmailChange).mockReturnValue(promise)
    const { user } = renderPage()

    await user.click(undoButton())
    await user.click(undoButton())

    expect(undoButton()).toHaveTextContent('Moving it back...')
    expect(undoEmailChange).toHaveBeenCalledTimes(1)
    await act(async () => finish({ email: 'old@example.com' }))
  })
})
