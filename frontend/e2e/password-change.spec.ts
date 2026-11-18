import { test, expect } from '@playwright/test'
import {
  askToChangePassword, emailTo, login, logout, memberSince, registerAndLogin, TEST_PASSWORD,
} from './helpers'
import { APP_NAME } from '../src/appInfo'

const NEW_PASSWORD = 'a brand new test passphrase'

test.describe('Password change', () => {
  test('changes it from the account page, keeps this device in and logs every other one out', async ({ page, browser }) => {
    const email = await registerAndLogin(page, 'e2e-password-change')
    const other = await browser.newPage()
    await other.goto('/login')
    await login(other, email)
    await other.goto('/account')
    await expect(memberSince(other)).toBeVisible()

    await page.goto('/account')
    await expect(memberSince(page)).toBeVisible()
    const dialog = await askToChangePassword(page, NEW_PASSWORD)
    await dialog.getByRole('button', { name: 'Save password' }).click()
    await expect(dialog).toBeHidden()
    await expect(page.getByText('Your password was changed. Every other device was logged out.')).toBeVisible()

    // This device stays signed in, across a reload too
    await page.reload()
    await expect(memberSince(page)).toBeVisible()

    // The other is turned away at its next request
    await other.reload()
    await expect(other).toHaveURL(/\/login/)
    await expect(other.getByRole('status')).toHaveText('Your session has ended. Please log in again.')
    await other.close()

    // The old password no longer logs in; the new one does
    await logout(page)
    await page.goto('/login')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill(TEST_PASSWORD)
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page.getByRole('alert')).toHaveText(/Invalid email or password/)
    await page.getByLabel('Email').clear()
    await page.getByLabel('Password').clear()
    await login(page, email, NEW_PASSWORD)

    expect((await emailTo(email, `Your ${APP_NAME} password was changed`)).Text)
      .toContain('changed from a signed-in session')
  })

  test('a wrong current password changes nothing, and says so on its field', async ({ page }) => {
    await registerAndLogin(page, 'e2e-password-wrong')
    await page.goto('/account')
    await expect(memberSince(page)).toBeVisible()

    const dialog = await askToChangePassword(page, NEW_PASSWORD, 'not my passphrase at all')
    await dialog.getByRole('button', { name: 'Save password' }).click()

    const current = dialog.getByLabel('Current password')
    await expect(current).toBeFocused()
    await expect(current).toHaveAccessibleDescription(/The password is incorrect/)
  })
})
