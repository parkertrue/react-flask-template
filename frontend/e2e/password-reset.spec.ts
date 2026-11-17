import { test, expect } from '@playwright/test'
import {
  createAccount, emailedLink, emailTo, expireAccessToken, fillReset, login, memberSince,
  requestReset, RESET_SUBJECT, uniqueEmail, UNSIGNED_RESET_LINK,
} from './helpers'
import { APP_NAME } from '../src/appInfo'

const NEW_PASSWORD = 'a brand new test passphrase'

test.describe('Password reset', () => {
  test('forgot password → email → new password → log in with it', async ({ page }) => {
    const email = uniqueEmail('e2e-reset')
    await createAccount(email)

    // From the login page
    await page.goto('/login')
    await page.getByRole('link', { name: 'Forgot your password?' }).click()
    // The login page has an Email field too: wait until it has gone
    await expect(page.getByRole('heading', { level: 1, name: 'Reset your password' })).toBeVisible()
    await expect(page).toHaveURL(/\/password-reset$/)
    await requestReset(page, email)
    await expect(page.getByRole('heading', { level: 1, name: 'Check your inbox' })).toBeFocused()

    // The emailed link opens the page that sets it, its token kept out of
    // the address bar
    await page.goto(await emailedLink(email, RESET_SUBJECT))
    await expect(page).toHaveURL(/\/password-reset\/complete$/)
    await expect(page.getByLabel('Email')).toHaveValue(email)
    await fillReset(page, NEW_PASSWORD)

    // Then to log in, with the new password alone
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('status')).toHaveText('Your password has been changed. Log in with the new one.')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill('a secure test passphrase')
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page.getByRole('alert')).toHaveText(/Invalid email or password/)
    await page.getByLabel('Email').clear()
    await page.getByLabel('Password').clear()
    await login(page, email, NEW_PASSWORD)

    // And the account's owner is told, in case it wasn't them
    expect((await emailTo(email, `Your ${APP_NAME} password was changed`)).Text)
      .toContain('every device signed in to the account was logged out')
  })

  test("ends the account's other sessions", async ({ page, browser }) => {
    const email = uniqueEmail('e2e-reset-sessions')
    await createAccount(email)
    const other = await browser.newPage()
    await other.goto('/login')
    await login(other, email)
    await other.goto('/account')
    await expect(memberSince(other)).toBeVisible()

    await page.goto('/password-reset')
    await requestReset(page, email)
    await page.goto(await emailedLink(email, RESET_SUBJECT))
    await fillReset(page, NEW_PASSWORD)
    await expect(page).toHaveURL(/\/login$/)

    // Its access token runs out within 15 minutes (DECISIONS.md); its
    // refresh is refused at once
    await expireAccessToken(other)
    await other.reload()
    await expect(other).toHaveURL(/\/login/)
    await expect(other.getByRole('status')).toHaveText('Your session has ended. Please log in again.')
    await other.close()
  })

  test('a link works once', async ({ page }) => {
    const email = uniqueEmail('e2e-reset-twice')
    await createAccount(email)
    await page.goto('/password-reset')
    await requestReset(page, email)
    const link = await emailedLink(email, RESET_SUBJECT)
    await page.goto(link)
    await fillReset(page, NEW_PASSWORD)
    await expect(page).toHaveURL(/\/login$/)

    await page.goto(link)
    await fillReset(page, 'yet another test passphrase')

    await expect(page.getByRole('alert')).toHaveText(/This link has already been used/)
    await expect(page.getByRole('alert')).toBeFocused()
    await expect(page.getByRole('link', { name: 'Ask for a new link' })).toHaveAttribute('href', '/password-reset')
  })

  test('a link this app never sent is refused', async ({ page }) => {
    await page.goto(UNSIGNED_RESET_LINK)
    await fillReset(page)

    await expect(page.getByRole('alert')).toHaveText(/This link is not valid/)
    await expect(page.getByRole('alert')).toBeFocused()
  })
})
