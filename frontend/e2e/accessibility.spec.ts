import { test, expect, type Page } from '@playwright/test'
import {
  askToDeleteAccount, askToLogoutAll, boxOf, expectNoCspViolations, expectNoViolations, expectReflow,
  expectTargetSize, expectVisibleFocus, expireAccessToken, fillRegistration, holdRequests, memberSince,
  register, registerAndLogin, serviceUnavailable, uniqueEmail,
} from './helpers'
import { APP_NAME } from '../src/appName'

// Path, title, h1, and how many Tab stops the page has (its navbar's three
// and the footer's three included)
const VISITOR_PAGES: [string, string, string, number][] = [
  ['/', APP_NAME, `Welcome to ${APP_NAME}`, 8],
  ['/login', `Log in | ${APP_NAME}`, 'Log in', 10],
  ['/register', `Register | ${APP_NAME}`, 'Register', 14],
  ['/privacy', `Privacy notice | ${APP_NAME}`, 'Privacy notice', 9],
  ['/terms', `Terms of service | ${APP_NAME}`, 'Terms of service', 8],
  ['/contact', `Contact | ${APP_NAME}`, 'Contact', 10],
  ['/no-such-page', `Page not found | ${APP_NAME}`, 'Page not found', 7],
]

/** Fill in the login form and submit it, without waiting */
async function submitLogin(page: Page, email = 'someone@example.com') {
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('SecurePass123')
  await page.getByRole('button', { name: 'Log in' }).click()
}

test.describe('Accessibility', () => {
  // These tests visit every page, so anything the app does that the CSP
  // blocks fails here. A feature's own pages are checked in its spec.
  expectNoCspViolations(test)

  test.describe('a visitor', () => {
    for (const [path, title, heading, stopCount] of VISITOR_PAGES) {
      test(`${path} has a title, a heading and no violations`, async ({ page }) => {
        await page.goto(path)

        await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
        await expect(page).toHaveTitle(title)
        await expectNoViolations(page)
      })

      test(`${path} reflows, shows focus and has large enough targets`, async ({ page }) => {
        await page.goto(path)
        await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()

        await expectReflow(page)
        await expectVisibleFocus(page, stopCount)
        await expectTargetSize(page)
      })
    }

    test('form errors are announced and pass', async ({ page }) => {
      await page.goto('/register')
      await page.getByRole('button', { name: 'Register' }).click()

      await expect(page.getByLabel('Email')).toBeFocused()
      await expectNoViolations(page)
      await expectReflow(page)
      await expectTargetSize(page)
    })

    // Layout moves focus on every change of path, the browser's own back
    // and forward included, so a screen reader names the page reached
    test('back and forward focus the page\'s heading', async ({ page }) => {
      await page.goto('/')
      await page.getByRole('link', { name: 'Log in' }).first().click()
      await expect(page.getByRole('heading', { level: 1, name: 'Log in' })).toBeFocused()

      await page.goBack()
      await expect(page.getByRole('heading', { level: 1, name: `Welcome to ${APP_NAME}` }))
        .toBeFocused()

      await page.goForward()
      await expect(page.getByRole('heading', { level: 1, name: 'Log in' })).toBeFocused()
    })

    // Forced colors (Windows High Contrast) drop backgrounds, so a button's
    // only edge, and a field needs its border to show where it is
    test('buttons and fields keep an edge in forced-colors mode', async ({ page }) => {
      await page.emulateMedia({ forcedColors: 'active' })
      await page.goto('/login')

      await expect(page.getByRole('button', { name: 'Log in' })).toHaveCSS('border-top-style', 'solid')
      await expect(page.getByLabel('Email')).toHaveCSS('border-top-style', 'solid')
      await expect(page.getByLabel('Email')).toHaveCSS('border-top-width', '1px')

      // And the keyboard's focus ring with them
      await page.getByLabel('Email').focus()
      await page.keyboard.press('Tab')
      await expect(page.getByLabel('Password')).toBeFocused()
      await expect(page.getByLabel('Password')).toHaveCSS('outline-style', 'solid')
    })

    test('logging in, busy and then failed, has no violations', async ({ page }) => {
      const release = await holdRequests(page, 'POST', '**/api/auth/login', serviceUnavailable)
      await page.goto('/login')
      await submitLogin(page)

      await expect(page.getByRole('button', { name: 'Logging in...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
      await expectReflow(page)
      await expectTargetSize(page)
    })

    test('registering, busy, has no violations', async ({ page }) => {
      const release = await holdRequests(page, 'POST', '**/api/auth/register', serviceUnavailable)
      await page.goto('/register')
      await fillRegistration(page, uniqueEmail('e2e-a11y-busy'))

      await expect(page.getByRole('button', { name: /creating account/i })).toBeVisible()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toBeVisible()
    })

    test('the login page after registering has no violations', async ({ page }) => {
      await register(page, uniqueEmail('e2e-a11y-registered'))

      await expect(page.getByRole('status')).toHaveText('Registration successful. Please log in.')
      await expectNoViolations(page)
    })
  })

  test.describe('a signed-in user', () => {
    test.beforeEach(async ({ page }) => {
      await registerAndLogin(page, 'e2e-a11y')
    })

    test('the account page is reached from the navbar, and has no violations', async ({ page }) => {
      await page.getByRole('link', { name: /\(account\)$/ }).click()

      await expect(page).toHaveTitle(`Account | ${APP_NAME}`)
      // Focus moved to the new page's heading, which a screen reader reads
      await expect(page.getByRole('heading', { level: 1, name: 'Account' })).toBeFocused()
      await expect(memberSince(page)).toBeVisible()
      await expectNoViolations(page)
    })

    test('the account page reflows, shows focus and has large enough targets', async ({ page }) => {
      await page.goto('/account')
      await expect(memberSince(page)).toBeVisible()

      await expectReflow(page)
      await expectVisibleFocus(page, 10)
      await expectTargetSize(page)
    })

    test('the account page, loading and then failed, has no violations', async ({ page }) => {
      const release = await holdRequests(page, 'GET', '**/api/account', serviceUnavailable)
      await page.goto('/account')

      await expect(page.getByText('Loading account details...')).toBeVisible()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
    })

    test('downloading the data, busy and then failed, has no violations', async ({ page }) => {
      await page.goto('/account')
      await expect(memberSince(page)).toBeVisible()
      const release = await holdRequests(page, 'GET', '**/api/account/export', serviceUnavailable)

      await page.getByRole('button', { name: 'Download your data' }).click()

      await expect(page.getByRole('button', { name: 'Preparing download...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expect(page.getByRole('button', { name: 'Download your data' })).toBeFocused()
      await expectNoViolations(page)
    })

    // ConfirmDialog, checked here so that no feature's spec has to keep it
    test('logging out all devices, asking, busy and then failed, has no violations', async ({ page }) => {
      await page.goto('/account')
      await expect(memberSince(page)).toBeVisible()

      let dialog = await askToLogoutAll(page)
      await expectNoViolations(page)
      await expectReflow(page)
      await expectTargetSize(page)
      // The modal keeps Tab inside it: its two buttons
      await expectVisibleFocus(page, 2)

      // Escape keeps the session, and focus goes back to the button that asked
      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden()
      await expect(page.getByRole('button', { name: 'Log out all devices' })).toBeFocused()
      await expect(memberSince(page)).toBeVisible()

      dialog = await askToLogoutAll(page)
      const release = await holdRequests(page, 'POST', '**/api/auth/logout-all', serviceUnavailable)
      await dialog.getByRole('button', { name: 'Log out all devices' }).click()

      // The dialog closes on the answer; the page's button is busy, focused
      await expect(dialog).toBeHidden()
      await expect(page.getByRole('button', { name: 'Logging out...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
    })

    // FormDialog, checked here so that no feature's spec has to keep it
    test('deleting the account, asking, busy and then failed, has no violations', async ({ page }) => {
      await page.goto('/account')
      await expect(memberSince(page)).toBeVisible()

      let dialog = await askToDeleteAccount(page)
      await expectNoViolations(page)
      await expectReflow(page)
      await expectTargetSize(page)
      // The password field and the two buttons
      await expectVisibleFocus(page, 3)
      // Centered, not pinned to a corner by the CSS reset's margin: 0
      const box = await boxOf(dialog)
      expect(Math.abs(box.x + box.width / 2 - (page.viewportSize()?.width ?? 0) / 2)).toBeLessThan(2)
      // Its border is transparent until forced colors drop the background
      await page.emulateMedia({ forcedColors: 'active' })
      await expect(dialog).not.toHaveCSS('border-top-color', 'rgba(0, 0, 0, 0)')
      await expect(dialog).toHaveCSS('border-top-width', '1px')
      await page.emulateMedia({ forcedColors: 'none' })

      // Escape keeps the account, and focus goes back to the button that asked
      await page.keyboard.press('Escape')
      await expect(dialog).toBeHidden()
      await expect(page.getByRole('button', { name: 'Delete account' })).toBeFocused()

      dialog = await askToDeleteAccount(page)
      const release = await holdRequests(page, 'POST', '**/api/account/delete', serviceUnavailable)
      await dialog.getByRole('button', { name: 'Delete account' }).click()
      // The dialog stays, its button busy and still focused, and Escape
      // cannot close it mid-request, pressed once or twice
      await expect(dialog.getByRole('button', { name: 'Deleting...' })).toBeFocused()
      await page.keyboard.press('Escape')
      await page.keyboard.press('Escape')
      await expect(dialog).toBeVisible()
      await expectNoViolations(page)

      release()
      await expect(dialog.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
    })

    // A page that crashes after the app has shown: the router's error page
    // takes focus. Nothing the API can answer crashes a shared page, so the
    // date formatting it calls throws instead
    test('the error page has no violations, and takes focus', async ({ page }) => {
      await page.goto('/')
      await page.evaluate(() => {
        Date.prototype.toLocaleDateString = () => { throw new Error('Planted crash') }
      })
      await page.getByRole('link', { name: /\(account\)$/ }).click()

      await expect(page.getByRole('heading', { level: 1, name: 'Something went wrong' }))
        .toBeFocused()
      await expectNoViolations(page)
      await expectReflow(page)
      await expectVisibleFocus(page, 8)
      await expectTargetSize(page)
    })

    test('the login page after deleting the account has no violations', async ({ page }) => {
      await page.goto('/account')
      await expect(memberSince(page)).toBeVisible()
      const dialog = await askToDeleteAccount(page)

      await dialog.getByRole('button', { name: 'Delete account' }).click()

      await expect(page.getByRole('status')).toHaveText('Your account has been deleted.')
      await expectNoViolations(page)
    })

    // The refresh cookie is gone, so the refresh is refused just as when the
    // session's time is up or another device logged out everywhere
    test('a session that ends on its own says so on the login page', async ({ page, context }) => {
      await page.goto('/account')
      await expect(memberSince(page)).toBeVisible()
      await expireAccessToken(page)
      await context.clearCookies()

      await page.reload()

      await expect(page).toHaveURL(/\/login/)
      await expect(page.getByRole('status'))
        .toHaveText('Your session has ended. Please log in again.')
      await expectNoViolations(page)
    })
  })
})
