import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import PasswordResetPage from '../PasswordResetPage'
import { requestPasswordReset } from '@/auth/authService'
import { renderRoutes } from '@/test/router'
import { APP_NAME } from '@/appInfo'

vi.mock('@/auth/authService')

// The steps themselves (sending again, another address, failures, busy
// states) are EmailLinkRequest's, tested through RegisterPage.test.tsx
function renderPage() {
  return renderRoutes([{ path: '/password-reset', element: <PasswordResetPage /> }], '/password-reset')
}

const email = () => screen.getByLabelText(/^Email/)

describe('PasswordResetPage', () => {
  it('asks for the account\'s email, says what it is for, and offers to log in', () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Reset your password' })).toBeInTheDocument()
    expect(email()).toHaveAttribute('autocomplete', 'email')
    expect(email()).toHaveAccessibleDescription(
      "The one your account uses. We'll email it a link to choose a new password.")
    expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
    expect(document.title).toBe(`Reset your password | ${APP_NAME}`)
  })

  it('sends the link, and says so without saying whether the address has an account', async () => {
    vi.mocked(requestPasswordReset).mockResolvedValue()
    const { user } = renderPage()
    await user.type(email(), 'user@example.com')

    await user.click(screen.getByRole('button', { name: 'Send link' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Check your inbox' })).toHaveFocus()
    expect(screen.getByText(/has an account, we sent it a link/)).toHaveTextContent(
      'If user@example.com has an account, we sent it a link. Open it within 60 minutes to choose a new password.')
    expect(requestPasswordReset).toHaveBeenCalledExactlyOnceWith('user@example.com')
  })
})
