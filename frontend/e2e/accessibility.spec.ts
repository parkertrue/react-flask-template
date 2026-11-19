import { test, expect, type Page } from '@playwright/test'
import {
  askToDeleteAccount, askToLogoutAll, boxOf, expectNoCspViolations, expectNoViolations, expectReflow,
  expectTargetSize, expectVisibleFocus, expireAccessToken, fillRegistration, fillReset, holdRequests,
  memberSince, registerAndLogin, requestLink, requestReset, serviceUnavailable, uniqueEmail, UNSIGNED_LINK,
  UNSIGNED_RESET_LINK, UNSIGNED_CHANGE_LINK, UNSIGNED_UNDO_LINK, askToChangeEmail, askToChangePassword,
} from './helpers'
import { APP_NAME } from '../src/appInfo'

// Path, title, h1, and how many Tab stops the page has (its navbar's three
// and the footer's three included)
const VISITOR_PAGES: [string, string, string, number][] = [
  ['/', APP_NAME, `Welcome to ${APP_NAME}`, 8],
  ['/login', `Log in | ${APP_NAME}`, 'Log in', 11],
  ['/signup', `Sign up | ${APP_NAME}`, 'Sign up', 9],
  // Without the emailed link: what to do instead
  ['/signup/complete', `Finish signing up | ${APP_NAME}`, 'Finish signing up', 7],
  ['/password-reset', `Reset your password | ${APP_NAME}`, 'Reset your password', 9],
  ['/password-reset/complete', `Choose a new password | ${APP_NAME}`, 'Choose a new password', 7],
  ['/account/email/complete', `Confirm your new email | ${APP_NAME}`, 'Confirm your new email', 7],
  ['/account/email/undo', `Undo an email change | ${APP_NAME}`, 'Undo an email change', 7],
  ['/privacy', `Privacy notice | ${APP_NAME}`, 'Privacy notice', 9],
  ['/terms', `Terms of service | ${APP_NAME}`, 'Terms of service', 8],
  ['/contact', `Contact | ${APP_NAME}`, 'Contact', 10],
  ['/no-such-page', `Page not found | ${APP_NAME}`, 'Page not found', 7],
]

/** Fill in the login form and submit it, without waiting */
async function submitLogin(page: Page, email = 'someone@example.com') {
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('a secure test passphrase')
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
      await page.goto('/signup')
      await page.getByRole('button', { name: 'Continue' }).click()

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

    test('asking for a link, busy and then failed, has no violations', async ({ page }) => {
      const release = await holdRequests(page, 'POST', '**/api/auth/register', serviceUnavailable)
      await page.goto('/signup')
      await requestLink(page, uniqueEmail('e2e-a11y-busy'))

      await expect(page.getByRole('button', { name: 'Sending link...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
    })

    test('the check-your-inbox step has no violations, reflows, shows focus and has large enough targets', async ({ page }) => {
      await page.goto('/signup')
      // Long, with nowhere to break, as an address can be: it must wrap
      await requestLink(page, uniqueEmail('e2e-a11y-inbox-of-a-rather-long-address'))

      await expect(page.getByRole('heading', { level: 1, name: 'Check your inbox' })).toBeFocused()
      await expect(page).toHaveTitle(`Check your inbox | ${APP_NAME}`)
      await expectNoViolations(page)
      await expectReflow(page)
      // The navbar's and footer's, and the two buttons
      await expectVisibleFocus(page, 8)
      await expectTargetSize(page)
    })

    test('sending the link again, busy and then failed, has no violations', async ({ page }) => {
      await page.goto('/signup')
      await requestLink(page, uniqueEmail('e2e-a11y-again'))
      await expect(page.getByRole('heading', { level: 1, name: 'Check your inbox' })).toBeFocused()
      const release = await holdRequests(page, 'POST', '**/api/auth/register', serviceUnavailable)

      await page.getByRole('button', { name: 'Send again' }).click()

      await expect(page.getByRole('button', { name: 'Sending...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
      await expectReflow(page)
    })

    test("the link's page has no violations, reflows, shows focus and has large enough targets", async ({ page }) => {
      await page.goto(UNSIGNED_LINK)

      await expect(page.getByLabel('Email')).toHaveValue('someone@example.com')
      await expectNoViolations(page)
      await expectReflow(page)
      // The navbar's and footer's, the four fields (the read-only email
      // too), the two links in the checkbox's label, and the button
      await expectVisibleFocus(page, 13)
      await expectTargetSize(page)
    })

    test("finishing, busy and then failed, has no violations", async ({ page }) => {
      const release = await holdRequests(page, 'POST', '**/api/auth/register/complete', serviceUnavailable)
      await page.goto(UNSIGNED_LINK)
      await fillRegistration(page)

      await expect(page.getByRole('button', { name: 'Creating account...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
    })

    test("the link's page, with every field refused, has no violations, and focuses the first", async ({ page }) => {
      await page.goto(UNSIGNED_LINK)

      await page.getByRole('button', { name: 'Create account' }).click()

      const password = page.getByLabel('Password', { exact: true })
      await expect(password).toBeFocused()
      await expect(password).toHaveAttribute('aria-invalid', 'true')
      await expectNoViolations(page)
      await expectReflow(page)
    })

    test("a breached password is the field's own message, focused, with no violations", async ({ page }) => {
      await page.route('**/api/auth/register/complete', route => route.fulfill({
        status: 422,
        json: { error: { code: 'PASSWORD_BREACHED', message: 'This password has appeared in a data breach. Choose another.' } },
      }))
      await page.goto(UNSIGNED_LINK)
      await fillRegistration(page)

      const password = page.getByLabel('Password', { exact: true })
      await expect(password).toBeFocused()
      await expect(password).toHaveAccessibleDescription(/appeared in a data breach/)
      await expectNoViolations(page)
    })

    test('read-only fields look inactive, busy ones included', async ({ page }) => {
      const release = await holdRequests(page, 'POST', '**/api/auth/register/complete', serviceUnavailable)
      await page.goto(UNSIGNED_LINK)
      const background = (label: string) => page.getByLabel(label, { exact: true })
        .evaluate(el => getComputedStyle(el).backgroundColor)
      const readOnly = await background('Email')
      expect(await background('Password')).not.toBe(readOnly)

      await fillRegistration(page)

      await expect(page.getByRole('button', { name: 'Creating account...' })).toBeFocused()
      expect(await background('Password')).toBe(readOnly)
      release()
      await expect(page.getByRole('alert')).toBeVisible()
    })

    test('a forged link has no violations, and focuses why', async ({ page }) => {
      await page.goto(UNSIGNED_LINK)
      await fillRegistration(page)

      await expect(page.getByRole('alert')).toHaveText(/This link is not valid/)
      await expect(page.getByRole('alert')).toBeFocused()
      await expectNoViolations(page)
      await expectReflow(page)
      await expectTargetSize(page)
    })

    // What the backend answers for a link it signed but won't take
    for (const [why, status, code, message] of [
      ['an expired link', 400, 'LINK_EXPIRED', /This link has expired/],
      ['a link used for an account since deleted', 400, 'LINK_USED', /already been used/],
      ['a link that made its account already', 409, 'EMAIL_ALREADY_REGISTERED', /already set up/],
    ] as const) {
      test(`${why} has no violations, and focuses why`, async ({ page }) => {
        await page.route('**/api/auth/register/complete', route => route.fulfill({
          status, json: { error: { code, message: 'refused' } },
        }))
        await page.goto(UNSIGNED_LINK)
        await fillRegistration(page)

        await expect(page.getByRole('alert')).toHaveText(message)
        await expect(page.getByRole('alert')).toBeFocused()
        await expectNoViolations(page)
        await expectReflow(page)
        await expectTargetSize(page)
      })
    }
  })

  test.describe("a password reset's pages", () => {
    test('asking for a link, busy and then failed, has no violations', async ({ page }) => {
      const release = await holdRequests(page, 'POST', '**/api/auth/password-reset', serviceUnavailable)
      await page.goto('/password-reset')
      await requestReset(page, uniqueEmail('e2e-a11y-reset-busy'))

      await expect(page.getByRole('button', { name: 'Sending link...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
    })

    test('the check-your-inbox step has no violations, reflows, shows focus and has large enough targets', async ({ page }) => {
      await page.goto('/password-reset')
      await requestReset(page, uniqueEmail('e2e-a11y-reset-inbox-of-a-rather-long-address'))

      await expect(page.getByRole('heading', { level: 1, name: 'Check your inbox' })).toBeFocused()
      await expectNoViolations(page)
      await expectReflow(page)
      // The navbar's and footer's, and the two buttons
      await expectVisibleFocus(page, 8)
      await expectTargetSize(page)
    })

    test("the link's page has no violations, reflows, shows focus and has large enough targets", async ({ page }) => {
      await page.goto(UNSIGNED_RESET_LINK)

      await expect(page.getByLabel('Email')).toHaveValue('someone@example.com')
      await expectNoViolations(page)
      await expectReflow(page)
      // The navbar's and footer's, the three fields (the read-only email
      // too), and the button
      await expectVisibleFocus(page, 10)
      await expectTargetSize(page)
    })

    test('saving, busy and then failed, has no violations', async ({ page }) => {
      const release = await holdRequests(page, 'POST', '**/api/auth/password-reset/complete', serviceUnavailable)
      await page.goto(UNSIGNED_RESET_LINK)
      await fillReset(page)

      await expect(page.getByRole('button', { name: 'Saving...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
    })

    test("the link's page, with every field refused, has no violations, and focuses the first", async ({ page }) => {
      await page.goto(UNSIGNED_RESET_LINK)

      await page.getByRole('button', { name: 'Save password' }).click()

      const password = page.getByLabel('New password', { exact: true })
      await expect(password).toBeFocused()
      await expect(password).toHaveAttribute('aria-invalid', 'true')
      await expectNoViolations(page)
      await expectReflow(page)
    })

    test('a refused link has no violations, and focuses why', async ({ page }) => {
      await page.goto(UNSIGNED_RESET_LINK)
      await fillReset(page)

      await expect(page.getByRole('alert')).toHaveText(/This link is not valid/)
      await expect(page.getByRole('alert')).toBeFocused()
      await expectNoViolations(page)
      await expectReflow(page)
      await expectTargetSize(page)
    })

    test('the login page after a reset has no violations', async ({ page }) => {
      await page.route('**/api/auth/password-reset/complete', route => route.fulfill({
        status: 200, json: { message: 'Password changed' },
      }))
      await page.goto(UNSIGNED_RESET_LINK)
      await fillReset(page)

      await expect(page).toHaveURL(/\/login$/)
      await expect(page.getByRole('status')).toHaveText('Your password has been changed. Log in with the new one.')
      await expectNoViolations(page)
    })
  })

  test.describe("an email change's link pages", () => {
    for (const [name, link, heading, button] of [
      ['the new address', UNSIGNED_CHANGE_LINK, 'Confirm your new email', 'Confirm new email'],
      ['the old address', UNSIGNED_UNDO_LINK, 'Undo an email change', 'Move my account back'],
    ] as const) {
      test(`${name}'s page has no violations, reflows, shows focus and has large enough targets`, async ({ page }) => {
        await page.goto(link)

        await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
        await expect(page.getByText('someone@example.com')).toBeVisible()
        await expectNoViolations(page)
        await expectReflow(page)
        // The navbar's and footer's, and the button
        await expectVisibleFocus(page, 7)
        await expectTargetSize(page)
      })

      test(`${name}'s page, busy and then refused, has no violations, and focuses why`, async ({ page }) => {
        const release = await holdRequests(page, 'POST', '**/api/account/email/*', serviceUnavailable)
        await page.goto(link)
        await page.getByRole('button', { name: button }).click()
        await expect(page.getByRole('button', { name: /\.\.\.$/ })).toBeFocused()
        await expectNoViolations(page)

        release()
        await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
        await expectNoViolations(page)
        await page.unrouteAll({ behavior: 'ignoreErrors' })
        await page.getByRole('button', { name: button }).click()
        await expect(page.getByRole('alert')).toHaveText(/This link is not valid/)
        await expect(page.getByRole('alert')).toBeFocused()
        await expectNoViolations(page)
        await expectTargetSize(page)
      })
    }
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
      await expectVisibleFocus(page, 12)
      await expectTargetSize(page)
    })

    test('changing the password, asking, busy and then failed, has no violations', async ({ page }) => {
      await page.goto('/account')
      await expect(memberSince(page)).toBeVisible()

      const dialog = await askToChangePassword(page, 'a brand new test passphrase')
      await expectNoViolations(page)
      await expectReflow(page)
      await expectTargetSize(page)
      // The read-only email, the three passwords and the two buttons
      await expectVisibleFocus(page, 6)

      const release = await holdRequests(page, 'POST', '**/api/account/password', serviceUnavailable)
      await dialog.getByRole('button', { name: 'Save password' }).click()
      await expect(dialog.getByRole('button', { name: 'Saving...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(dialog.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
    })

    test('changing the email, asking, busy and then failed, has no violations', async ({ page }) => {
      await page.goto('/account')
      await expect(memberSince(page)).toBeVisible()

      const dialog = await askToChangeEmail(page, uniqueEmail('e2e-a11y-moved'))
      await expectNoViolations(page)
      await expectReflow(page)
      await expectTargetSize(page)
      // The two fields and the two buttons
      await expectVisibleFocus(page, 4)

      const release = await holdRequests(page, 'POST', '**/api/account/email', serviceUnavailable)
      await dialog.getByRole('button', { name: 'Send link' }).click()
      await expect(dialog.getByRole('button', { name: 'Sending link...' })).toBeFocused()
      await expectNoViolations(page)

      release()
      await expect(dialog.getByRole('alert')).toHaveText(/temporarily unavailable/)
      await expectNoViolations(page)
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

      // The account page has a status line of its own; wait until it is gone
      await expect(page).toHaveURL(/\/login$/)
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
