import { test, expect } from '@playwright/test'
import {
  askToChangeEmail, emailedLink, login, logout, memberSince, registerAndLogin, TEST_PASSWORD, uniqueEmail,
} from './helpers'
import { APP_NAME } from '../src/appInfo'

const CONFIRM_SUBJECT = `Confirm your new ${APP_NAME} email`
const CHANGED_SUBJECT = `Your ${APP_NAME} email was changed`

test.describe('Email change', () => {
  test('account → new address → its link → the account moves, and the old address can move it back', async ({ page }) => {
    const oldEmail = await registerAndLogin(page, 'e2e-change-old')
    const newEmail = uniqueEmail('e2e-change-new')

    // Asked from the account page, with the password
    await page.goto('/account')
    await expect(memberSince(page)).toBeVisible()
    const dialog = await askToChangeEmail(page, newEmail)
    await dialog.getByRole('button', { name: 'Send link' }).click()
    await expect(dialog).toBeHidden()
    await expect(page.getByText(`We sent a link to ${newEmail}.`)).toBeVisible()

    // The new address's link moves it, and this browser shows it at once
    await page.goto(await emailedLink(newEmail, CONFIRM_SUBJECT))
    await expect(page).toHaveURL(/\/account\/email\/complete$/)
    await page.getByRole('button', { name: 'Confirm new email' }).click()
    await expect(page.getByText(/^Your email is now/)).toBeFocused()
    await expect(page.getByRole('link', { name: `${newEmail} (account)` })).toBeVisible()

    // It logs in from now on
    await logout(page)
    await page.goto('/login')
    await login(page, newEmail)

    // The old address was told, and its link moves the account back,
    // logging every device out
    await page.goto(await emailedLink(oldEmail, CHANGED_SUBJECT))
    await page.getByRole('button', { name: 'Move my account back' }).click()
    await expect(page.getByText(/^Your account is back at/)).toBeFocused()
    await expect(page.getByRole('link', { name: 'Reset your password' })).toHaveAttribute('href', '/password-reset')
    await expect(page.getByRole('link', { name: /\(account\)$/ })).toBeHidden()
    await page.goto('/login')
    await login(page, oldEmail, TEST_PASSWORD)
  })

  test('another device signed in to the account shows the new address once it looks again', async ({ page, browser }) => {
    const oldEmail = await registerAndLogin(page, 'e2e-change-device')
    const newEmail = uniqueEmail('e2e-change-device-new')
    const other = await browser.newPage()
    await other.goto('/login')
    await login(other, oldEmail)
    await other.goto('/account')
    await expect(memberSince(other)).toBeVisible()

    await page.goto('/account')
    const dialog = await askToChangeEmail(page, newEmail)
    await dialog.getByRole('button', { name: 'Send link' }).click()
    await expect(dialog).toBeHidden()
    await page.goto(await emailedLink(newEmail, CONFIRM_SUBJECT))
    await page.getByRole('button', { name: 'Confirm new email' }).click()
    await expect(page.getByText(/^Your email is now/)).toBeVisible()

    await other.reload()
    await expect(other.getByRole('link', { name: `${newEmail} (account)` })).toBeVisible()
    await other.close()
  })

  test('a wrong password moves nothing, and says so on its field', async ({ page }) => {
    await registerAndLogin(page, 'e2e-change-wrong')
    await page.goto('/account')
    await expect(memberSince(page)).toBeVisible()

    const dialog = await askToChangeEmail(page, uniqueEmail('e2e-change-wrong-new'), 'not my passphrase at all')
    await dialog.getByRole('button', { name: 'Send link' }).click()

    const password = dialog.getByLabel('Password')
    await expect(password).toBeFocused()
    await expect(password).toHaveAccessibleDescription(/The password is incorrect/)
  })
})
