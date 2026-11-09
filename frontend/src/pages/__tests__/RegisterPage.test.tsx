import { describe, it, expect, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import RegisterPage from '../RegisterPage'
import { requestRegistration } from '@/auth/authService'
import { errorBody, httpError } from '@/test/fixtures'
import { renderRoutes } from '@/test/router'
import { APP_NAME } from '@/appName'

vi.mock('@/auth/authService')

function renderPage() {
  return renderRoutes([{ path: '/register', element: <RegisterPage /> }], '/register')
}

const email = () => screen.getByLabelText(/^Email/)
const continueButton = () => screen.getByRole('button', { name: /continue|sending link/i })
const sendAgain = () => screen.getByRole('button', { name: /send again|sending/i })
const useAnother = () => screen.getByRole('button', { name: 'Use a different email' })

async function sendLink(address = 'user@example.com') {
  const rendered = renderPage()
  await rendered.user.type(email(), address)
  await rendered.user.click(continueButton())
  return rendered
}

describe('RegisterPage', () => {
  it('asks for the email alone, says what it is for, and offers to log in', () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Register' })).toBeInTheDocument()
    expect(email()).toHaveAttribute('autocomplete', 'email')
    expect(email()).toHaveAccessibleDescription("We'll email you a link to choose a password.")
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Privacy notice' })).toHaveAttribute('href', '/privacy')
    expect(screen.getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
    expect(document.title).toBe(`Register | ${APP_NAME}`)
  })

  // One example per message: the rules themselves are covered in validation.test.ts
  it.each([
    ['an empty email', 'x{Backspace}', 'Email is required'],
    ['a malformed email', 'not-an-email', 'Please enter a valid email address'],
  ])('stops %s, explains, and focuses the field', async (_, typed, message) => {
    const { user } = renderPage()
    await user.type(email(), typed)

    await user.click(continueButton())

    expect(email()).toHaveAttribute('aria-invalid', 'true')
    expect(email()).toHaveAccessibleDescription(expect.stringContaining(message))
    expect(email()).toHaveFocus()
    expect(requestRegistration).not.toHaveBeenCalled()
  })

  describe('once the link is sent', () => {
    it('says to check the inbox, names the address and focuses the heading', async () => {
      vi.mocked(requestRegistration).mockResolvedValue()

      await sendLink()

      expect(await screen.findByRole('heading', { level: 1, name: 'Check your inbox' })).toHaveFocus()
      expect(screen.getByText('user@example.com')).toBeInTheDocument()
      expect(document.title).toBe(`Check your inbox | ${APP_NAME}`)
      expect(requestRegistration).toHaveBeenCalledExactlyOnceWith('user@example.com')
    })

    it('sends it again, and says so on the status line', async () => {
      vi.mocked(requestRegistration).mockResolvedValue()
      const { user } = await sendLink()
      await screen.findByRole('heading', { name: 'Check your inbox' })

      await user.click(sendAgain())

      await waitFor(() =>
        expect(screen.getByRole('status')).toHaveTextContent('Sent again to user@example.com.'))
      expect(requestRegistration).toHaveBeenCalledTimes(2)
      expect(requestRegistration).toHaveBeenLastCalledWith('user@example.com')
    })

    it('says why sending again failed, in place of the last "sent", and keeps the step', async () => {
      vi.mocked(requestRegistration)
        .mockResolvedValueOnce()
        .mockResolvedValueOnce()
        .mockRejectedValueOnce(httpError(429, errorBody('RATE_LIMITED', 'Too many requests, please try again later')))
      const { user } = await sendLink()
      await screen.findByRole('heading', { name: 'Check your inbox' })
      await user.click(sendAgain())
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Sent again'))

      await user.click(sendAgain())

      expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests')
      expect(screen.getByRole('status')).toHaveTextContent(/^$/)
      expect(sendAgain()).toHaveAttribute('aria-disabled', 'false')
    })

    it('goes back to the form, the address kept, for a different email', async () => {
      vi.mocked(requestRegistration).mockResolvedValue()
      const { user } = await sendLink()
      await screen.findByRole('heading', { name: 'Check your inbox' })

      await user.click(useAnother())

      expect(screen.getByRole('heading', { level: 1, name: 'Register' })).toHaveFocus()
      expect(email()).toHaveValue('user@example.com')
    })

    it('ignores the buttons while sending again', async () => {
      const { promise, resolve: finish } = Promise.withResolvers<undefined>()
      vi.mocked(requestRegistration).mockResolvedValueOnce().mockReturnValueOnce(promise)
      const { user } = await sendLink()
      await screen.findByRole('heading', { name: 'Check your inbox' })

      await user.click(sendAgain())
      await user.click(sendAgain())
      await user.click(useAnother())

      expect(sendAgain()).toHaveTextContent('Sending...')
      expect(sendAgain()).toHaveAttribute('aria-disabled', 'true')
      expect(useAnother()).toHaveAttribute('aria-disabled', 'true')
      expect(screen.getByRole('heading', { name: 'Check your inbox' })).toBeInTheDocument()
      expect(requestRegistration).toHaveBeenCalledTimes(2)
      await act(async () => finish(undefined))
    })
  })

  it.each([
    ['too many requests', httpError(429, errorBody('RATE_LIMITED', 'Too many requests, please try again later')),
      'Too many requests'],
    ['the network fails', new Error('Network Error'), 'Network error'],
  ])('announces why when %s, and lets the user try again', async (_, error, message) => {
    vi.mocked(requestRegistration).mockRejectedValue(error)

    await sendLink()

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(continueButton()).toHaveAttribute('aria-disabled', 'false')
    expect(email()).not.toHaveAttribute('readonly')
  })

  it('keeps focus and ignores repeat submits while the request is in flight', async () => {
    const { promise, resolve: finish } = Promise.withResolvers<undefined>()
    vi.mocked(requestRegistration).mockReturnValue(promise)
    const { user } = await sendLink()

    await user.click(continueButton())

    expect(continueButton()).toHaveTextContent('Sending link...')
    expect(continueButton()).toHaveAttribute('aria-disabled', 'true')
    expect(continueButton()).toHaveFocus()
    expect(email()).toHaveAttribute('readonly')
    expect(requestRegistration).toHaveBeenCalledTimes(1)
    await act(async () => finish(undefined))
  })
})
