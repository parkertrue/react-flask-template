import { test, expect } from '@playwright/test'
import {
  askToDeleteAccount, downloadData, emailedLink, emailTo, expectNoViolations, fillRegistration, login,
  logout, memberSince, openAccount, register, registerAndLogin, requestLink, TEST_PASSWORD, uniqueEmail,
} from './helpers'
import { APP_NAME } from '../src/appName'

test.describe('Critical User Journey', () => {
  let testEmail: string

  test.beforeEach(() => {
    testEmail = uniqueEmail('e2e-test')
  })

  test('complete user journey: register → email → account → logout → login', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: `Welcome to ${APP_NAME}` })).toBeVisible()

    // The home page's call to action leads to registration
    await page.getByRole('link', { name: /get started/i }).click()
    await expect(page).toHaveURL(/\/register/)
    await requestLink(page, testEmail)
    await expect(page.getByRole('heading', { level: 1, name: 'Check your inbox' })).toBeFocused()

    // The emailed link opens the page that finishes, its token kept out of
    // the address bar; finishing signs in
    await page.goto(await emailedLink(testEmail))
    await expect(page).toHaveURL(/\/register\/complete$/)
    await expect(page.getByLabel('Email')).toHaveValue(testEmail)
    await fillRegistration(page)
    await page.waitForURL(url => url.pathname !== '/register/complete', { timeout: 15000 })
    await openAccount(page)
    await expect(page.getByRole('main').getByText(testEmail, { exact: true })).toBeVisible()

    // The session survives a page load
    await page.reload()
    await expect(page).toHaveURL(/\/account/)
    await expect(memberSince(page)).toBeVisible()

    // Logging out returns home, and the account page then asks to log in
    await logout(page)
    await page.goto('/account')
    await expect(page).toHaveURL(/\/login/)
    await login(page, testEmail)
    await expect(page).toHaveURL(/\/account$/)
  })

  test('cannot access protected routes without authentication', async ({ page }) => {
    await page.goto('/account')

    await expect(page).toHaveURL(/\/login/)
    await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible()
  })

  test('login with invalid credentials shows error', async ({ page }) => {
    await page.goto('/login')

    await page.getByLabel(/email/i).fill('nonexistent@example.com')
    await page.getByLabel(/password/i).fill('WrongPassword123')
    await page.getByRole('button', { name: /^log in$|logging in/i }).click()

    await expect(page.getByRole('alert')).toHaveText(/invalid email or password/i)

    await expect(page).toHaveURL(/\/login/)
  })

  test('deleting the account ends the session, and its login with it', async ({ page }) => {
    const email = await registerAndLogin(page, 'e2e-delete')
    await openAccount(page)

    const dialog = await askToDeleteAccount(page)
    await dialog.getByRole('button', { name: 'Delete account' }).click()

    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Log in' })).toBeFocused()
    await expect(page.getByRole('status')).toHaveText('Your account has been deleted.')

    // The account is gone, not just signed out
    await page.getByLabel(/email/i).fill(email)
    await page.getByLabel(/password/i).fill(TEST_PASSWORD)
    await page.getByRole('button', { name: /^log in$/i }).click()
    await expect(page.getByRole('alert')).toHaveText(/invalid email or password/i)
  })

  test('downloading the data saves the account in a file, and says so', async ({ page }) => {
    const email = await registerAndLogin(page, 'e2e-export')
    await openAccount(page)

    const { filename, data } = await downloadData(page)

    expect(filename).toMatch(/-data-\d{4}-\d{2}-\d{2}\.json$/)
    expect(data.account.email).toBe(email)
    await expect(page.getByRole('status').filter({ hasText: 'Download started' }))
      .toHaveText(`Download started: ${filename}`)
  })

  test('deleting the account with a wrong password keeps it', async ({ page }) => {
    await registerAndLogin(page, 'e2e-delete-wrong')
    await openAccount(page)

    const dialog = await askToDeleteAccount(page, 'WrongPassword123')
    await dialog.getByRole('button', { name: 'Delete account' }).click()

    // The field's own message, focused, like a failed submit's
    const password = page.getByLabel('Password', { exact: true })
    await expect(password).toBeFocused()
    await expect(password).toHaveAttribute('aria-invalid', 'true')
    await expect(password).toHaveAccessibleDescription(/The password is incorrect/)
    await expect(page).toHaveURL(/\/account$/)
    await page.reload()
    await expect(memberSince(page)).toBeVisible()
  })

  // The page answers alike, so it never tells a stranger the address is
  // taken; the inbox's owner is told instead
  test('signing up with a registered email says so by email alone', async ({ page }) => {
    const existingEmail = uniqueEmail('existing')
    await register(page, existingEmail)
    await logout(page)

    await page.goto('/register')
    await requestLink(page, existingEmail)

    await expect(page.getByRole('heading', { level: 1, name: 'Check your inbox' })).toBeVisible()
    const message = await emailTo(existingEmail, 'You already have an account')
    expect(message.Text).toContain('/login')
    expect(message.Text).not.toContain('token=')
  })

  test('a link used twice says the account is set up, and offers to log in', async ({ page }) => {
    const email = uniqueEmail('e2e-twice')
    await page.goto('/register')
    await requestLink(page, email)
    const link = await emailedLink(email)
    await page.goto(link)
    await fillRegistration(page)
    await page.waitForURL(url => url.pathname !== '/register/complete')
    await logout(page)

    await page.goto(link)
    await fillRegistration(page)

    await expect(page.getByRole('alert')).toHaveText('This account is already set up.')
    await expect(page.getByRole('alert')).toBeFocused()
    await expect(page.getByRole('main').getByRole('link', { name: 'Log in' })).toHaveAttribute('href', '/login')
  })

  // The test stack checks no password against Pwned Passwords (a third
  // party), so the answer production would give is played here
  test('a breached password is explained on its field, which keeps focus', async ({ page }) => {
    await page.route('**/api/auth/register/complete', route => route.fulfill({
      status: 422,
      json: { error: {
        code: 'PASSWORD_BREACHED',
        message: 'This password has appeared in a data breach. Choose another.',
      } },
    }))
    await page.goto('/register/complete#email=someone%40example.com&token=a-token')
    await fillRegistration(page)

    const password = page.getByLabel(/^password$/i)
    await expect(password).toBeFocused()
    await expect(password).toHaveAccessibleDescription(
      /This password has appeared in a data breach\. Choose another\./)
    await expectNoViolations(page)
  })

  test('a link this app never sent is refused', async ({ page }) => {
    await page.goto('/register/complete#email=someone%40example.com&token=forged.token.here')
    await fillRegistration(page)

    await expect(page.getByRole('alert')).toHaveText(/This link is not valid/)
    await expect(page.getByRole('link', { name: 'Start again' })).toHaveAttribute('href', '/register')
  })
})
