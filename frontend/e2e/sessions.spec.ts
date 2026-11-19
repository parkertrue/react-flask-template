import { test, expect, type Browser } from '@playwright/test'
import {
  expectNoViolations, expectReflow, expectTargetSize, expectVisibleFocus, expireAccessToken, login,
  memberSince, registerAndLogin,
} from './helpers'

const FIREFOX_WINDOWS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0'

/** Another device, signed in to the account: its own browser context */
async function otherDevice(browser: Browser, email: string) {
  const context = await browser.newContext({ userAgent: FIREFOX_WINDOWS, ignoreHTTPSErrors: true })
  const page = await context.newPage()
  await page.goto('/login')
  await login(page, email)
  return { context, page }
}

test.describe('Sessions', () => {
  test('the account page lists every device, and logs one out', async ({ page, browser }) => {
    const email = await registerAndLogin(page, 'e2e-sessions')
    const other = await otherDevice(browser, email)

    await page.goto('/account')
    await expect(memberSince(page)).toBeVisible()
    const devices = page.getByRole('list', { name: 'Signed-in devices' }).getByRole('listitem')
    await expect(devices).toHaveCount(2)
    // In order of last activity, which loading this page may have just
    // refreshed: the other device's, and this one's, marked
    await expect(devices.filter({ hasText: 'Firefox on Windows' })).toHaveCount(1)
    await expect(devices.filter({ hasText: '(this device)' })).toHaveCount(1)
    await expect(devices.filter({ hasText: '(this device)' })).not.toContainText('Firefox on Windows')

    await page.getByRole('button', { name: 'Log out Firefox on Windows' }).click()

    await expect(devices).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Log out all devices' })).toBeFocused()
    await expect(page.getByText('Logged out Firefox on Windows.')).toBeAttached()

    // That device's next refresh is refused; this one stays signed in
    await other.page.goto('/account')
    await expireAccessToken(other.page)
    await other.page.reload()
    await expect(other.page).toHaveURL(/\/login/)
    await expect(other.page.getByRole('status')).toHaveText('Your session has ended. Please log in again.')
    await other.context.close()
    await page.reload()
    await expect(memberSince(page)).toBeVisible()
  })

  test('the list, with another device in it, has no violations, reflows, shows focus and has large enough targets', async ({ page, browser }) => {
    const email = await registerAndLogin(page, 'e2e-sessions-a11y')
    const other = await otherDevice(browser, email)

    await page.goto('/account')
    await expect(page.getByRole('button', { name: 'Log out Firefox on Windows' })).toBeVisible()

    await expectNoViolations(page)
    await expectReflow(page)
    // The account page's own, and the other device's Log out
    await expectVisibleFocus(page, 13)
    await expectTargetSize(page)
    await other.context.close()
  })
})
