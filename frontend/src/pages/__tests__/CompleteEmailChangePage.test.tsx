import { describe, it, expect, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import CompleteEmailChangePage from '../CompleteEmailChangePage'
import { completeEmailChange, getAccount } from '@/auth/authService'
import { storage } from '@/auth/storage'
import { account, errorBody, httpError, linkToken } from '@/test/fixtures'
import { renderRoutes, signIn } from '@/test/router'
import { APP_NAME } from '@/appInfo'

vi.mock('@/auth/authService')

const TOKEN = linkToken('new@example.com', '7:a1b2')
const LINK = `/account/email/complete#token=${TOKEN}`

function renderPage(entry = LINK) {
  return renderRoutes([{ path: '/account/email/complete', element: <CompleteEmailChangePage /> }], entry)
}

const confirmButton = () => screen.getByRole('button', { name: /confirm new email|confirming/i })

describe('CompleteEmailChangePage', () => {
  it("asks before moving the account to the token's address", () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Confirm your new email' })).toBeInTheDocument()
    expect(screen.getByText(/Move your account to/)).toHaveTextContent('Move your account to new@example.com?')
    expect(document.title).toBe(`Confirm your new email | ${APP_NAME}`)
    expect(completeEmailChange).not.toHaveBeenCalled()
  })

  it('takes the token off the address bar and out of history', async () => {
    const { router } = renderPage()

    await waitFor(() => expect(router.state.location.hash).toBe(''))
    expect(confirmButton()).toBeInTheDocument()
  })

  it('asks without an address when the token names none', () => {
    renderPage('/account/email/complete#token=garbage')

    expect(screen.getByText('Move your account to the address this link was sent to?')).toBeInTheDocument()
  })

  it('says what to do without a link', () => {
    renderPage('/account/email/complete')

    expect(screen.getByText(/This page needs the link from your email/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('moves the account and says where it is, offering to log in', async () => {
    vi.mocked(completeEmailChange).mockResolvedValue({ email: 'new@example.com' })
    const { user } = renderPage()

    await user.click(confirmButton())

    const done = await screen.findByText(/Your email is now/)
    expect(done).toHaveTextContent('Your email is now new@example.com. Log in with it from now on.')
    expect(done).toHaveFocus()
    expect(completeEmailChange).toHaveBeenCalledExactlyOnceWith(TOKEN)
    expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
    expect(getAccount).not.toHaveBeenCalled()
  })

  it("shows a signed-in browser its own account's address, whichever account it is", async () => {
    vi.mocked(completeEmailChange).mockResolvedValue({ email: 'new@example.com' })
    vi.mocked(getAccount).mockResolvedValue(account('new@example.com', '2026-01-15T10:30:00+00:00'))
    signIn('old@example.com')
    const { user } = renderPage()

    await user.click(confirmButton())

    await screen.findByText(/Your email is now/)
    expect(storage.getEmail()).toBe('new@example.com')
    expect(screen.getByRole('link', { name: 'Go to your account' })).toHaveAttribute('href', '/account')
  })

  it("still says it moved when this browser's account cannot be asked", async () => {
    vi.mocked(completeEmailChange).mockResolvedValue({ email: 'new@example.com' })
    vi.mocked(getAccount).mockRejectedValue(new Error('Network Error'))
    signIn('old@example.com')
    const { user } = renderPage()

    await user.click(confirmButton())

    expect(await screen.findByText(/Your email is now/)).toBeInTheDocument()
    expect(storage.getEmail()).toBe('old@example.com')
  })

  it.each([
    ['an expired link', 'LINK_EXPIRED', 'This link has expired.'],
    ['a link this app never sent', 'LINK_INVALID', 'This link is not valid.'],
    ['a link already used', 'LINK_USED', 'This link has already been used'],
    ['an address taken since', 'EMAIL_ALREADY_REGISTERED', 'Another account has this email address now'],
  ] as const)('replaces the button for %s, and focuses why', async (_, code, message) => {
    vi.mocked(completeEmailChange).mockRejectedValue(httpError(400, errorBody(code, 'x')))
    const { user } = renderPage()

    await user.click(confirmButton())

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(message)
    expect(alert).toHaveFocus()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('offers the account page to a signed-in user whose link was refused', async () => {
    vi.mocked(completeEmailChange).mockRejectedValue(httpError(400, errorBody('LINK_USED', 'x')))
    signIn('old@example.com')
    const { user } = renderPage()

    await user.click(confirmButton())

    await screen.findByRole('alert')
    expect(screen.getByRole('link', { name: 'Go to your account' })).toHaveAttribute('href', '/account')
  })

  it('announces why when the request fails otherwise, and lets the user try again', async () => {
    vi.mocked(completeEmailChange).mockRejectedValue(new Error('Network Error'))
    const { user } = renderPage()

    await user.click(confirmButton())

    expect(await screen.findByRole('alert')).toHaveTextContent('Network error')
    expect(confirmButton()).toHaveAttribute('aria-disabled', 'false')
  })

  it('ignores repeat clicks while the request is in flight', async () => {
    const { promise, resolve: finish } = Promise.withResolvers<{ email: string }>()
    vi.mocked(completeEmailChange).mockReturnValue(promise)
    const { user } = renderPage()

    await user.click(confirmButton())
    await user.click(confirmButton())

    expect(confirmButton()).toHaveTextContent('Confirming...')
    expect(confirmButton()).toHaveAttribute('aria-disabled', 'true')
    expect(completeEmailChange).toHaveBeenCalledTimes(1)
    await act(async () => finish({ email: 'new@example.com' }))
  })
})
