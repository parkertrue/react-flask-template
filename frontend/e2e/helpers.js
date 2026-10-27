import { expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { createHmac, randomUUID } from 'crypto'
import { readFileSync } from 'fs'
import path from 'path'
import { APP_NAME } from '../src/appName.js'
import { TERMS_VERSION } from '../src/legal.js'

export const TEST_PASSWORD = 'SecurePass123'

/** The body of a registration through the API, with the terms accepted */
export const registration = (email, password = TEST_PASSWORD) =>
  ({ email, password, terms_version: TERMS_VERSION })

// Every run registers fresh accounts, so emails must never repeat
export const uniqueEmail = (prefix) => `${prefix}-${randomUUID()}@example.com`

/** Fill in and submit the registration form on the page, without waiting */
export async function fillRegistration(page, email, password = TEST_PASSWORD) {
  await page.getByLabel(/email/i).fill(email)
  await page.getByLabel(/^password$/i).fill(password)
  await page.getByLabel(/confirm password/i).fill(password)
  await page.getByRole('checkbox', { name: /^I accept the Terms/ }).check()
  await page.getByRole('button', { name: /register|creating account/i }).click()
}

/** Open the registration page, then fill it in and submit it */
export async function submitRegistration(page, email, password = TEST_PASSWORD) {
  await page.goto('/register')
  await fillRegistration(page, email, password)
}

/** Register through the UI; the redirect to /login only follows a 201 */
export async function register(page, email, password = TEST_PASSWORD) {
  await submitRegistration(page, email, password)
  await expect(page).toHaveURL(/\/login/, { timeout: 10000 })
}

/** Log in from the login page and wait to be sent on from it */
export async function login(page, email, password = TEST_PASSWORD) {
  await page.getByLabel(/email/i).fill(email)
  await page.getByLabel(/password/i).fill(password)
  const loginButton = page.getByRole('button', { name: /^log in$|logging in/i })
  await expect(loginButton).toBeEnabled()
  await Promise.all([
    page.waitForURL(url => url.pathname !== '/login', { timeout: 15000 }),
    loginButton.click(),
  ])
}

/** A new account, logged in on the page login leads to; returns its email */
export async function registerAndLogin(page, prefix) {
  const email = uniqueEmail(prefix)
  await register(page, email)
  await login(page, email)
  return email
}

/** Log this device out from the navbar; it lands on the home page */
export async function logout(page) {
  // Exact: the account page also has "Log out all devices"
  await page.getByRole('button', { name: 'Log out', exact: true }).click()
  await expectHomeReached(page)
}

/** Open the account page from the navbar's email link, once it has loaded */
export async function openAccount(page) {
  await page.getByRole('link', { name: /\(account\)$/ }).click()
  await expect(memberSince(page)).toBeVisible()
}

/** The account page's line once GET /api/account has answered */
export const memberSince = page => page.getByText(/^Member since /)

/** Sign every device out from the account page, reached by the navbar's email */
export async function logoutAllDevices(page) {
  await page.getByRole('link', { name: /\(account\)$/ }).click()
  await page.getByRole('button', { name: 'Log out all devices' }).click()
  await expectHomeReached(page)
}

/**
 * On the account page, type the password and ask to delete the account;
 * returns the dialog that asks to confirm
 */
export async function askToDeleteAccount(page, password = TEST_PASSWORD) {
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Delete account' }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete your account?' })
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  return dialog
}

// The URL alone can pass on a home page that is replaced at once (by /login,
// if the session ended before home rendered); its focused h1 cannot
async function expectHomeReached(page) {
  await page.waitForURL(/\/$/)
  await expect(page.getByRole('heading', { level: 1, name: `Welcome to ${APP_NAME}` }))
    .toBeFocused()
}

// The E2E backend signs tokens with SECRET_KEY from .env.test, so a test can
// re-sign the page's own access token as already expired: exactly what the
// browser holds once the real 15-minute token lapses.
function signingKey() {
  const env = readFileSync(path.join(import.meta.dirname, '..', '..', '.env.test'), 'utf8')
  return env.match(/^SECRET_KEY=(.*)$/m)[1].trim()
}

/** Replace the page's access token with the same one, expired */
export async function expireAccessToken(page) {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  const [header, payload] = token.split('.')
  const claims = JSON.parse(Buffer.from(payload, 'base64url').toString())
  const now = Math.floor(Date.now() / 1000)
  const expired = Buffer.from(JSON.stringify({
    ...claims, iat: now - 3600, nbf: now - 3600, exp: now - 60,
  })).toString('base64url')
  const signature = createHmac('sha256', signingKey())
    .update(`${header}.${expired}`).digest('base64url')
  await page.evaluate(
    t => localStorage.setItem('access_token', t), `${header}.${expired}.${signature}`)
}

// axe checks what jsdom cannot, such as color contrast, against the WCAG 2.2
// A and AA rules. Each page is checked as rendered, with any error states shown.
// Its heading outline too: exactly one h1 (axe's own rule asks for at least
// one), and heading-order, which axe files under best practice
export async function expectNoViolations(page) {
  await expect(page.locator('h1')).toHaveCount(1)
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .options({ rules: { 'heading-order': { enabled: true } } })
    .analyze()
  // The rule ids and the offending markup, so a failure says what to fix
  expect(violations.map(v => ({ rule: v.id, nodes: v.nodes.map(n => n.html) }))).toEqual([])
}

/** What every outage answers with, nginx's 502/504 as much as the backend's 503 */
export const SERVICE_UNAVAILABLE_MESSAGE = readFileSync(
  path.join(import.meta.dirname, '..', '..', 'backend/app/utils/errors.py'), 'utf8',
).match(/^SERVICE_UNAVAILABLE_MESSAGE = '(.+)'$/m)[1]

/** The backend's answer while MySQL or Redis is down, word for word */
export const serviceUnavailable = {
  status: 503,
  json: { error: { code: 'SERVICE_UNAVAILABLE', message: SERVICE_UNAVAILABLE_MESSAGE } },
}

/**
 * Hold the page's `method` requests to `url` until the returned release()
 * is called, to show a busy state. Each then gets `answer` (route.fulfill
 * options), or goes through to the server when there is none.
 */
export async function holdRequests(page, method, url, answer) {
  let release
  const released = new Promise(resolve => { release = resolve })
  await page.route(url, async route => {
    if (route.request().method() !== method) return route.fallback()
    await released
    return answer ? route.fulfill(answer) : route.fallback()
  })
  return release
}

// The text-spacing overrides WCAG 1.4.12 says content must survive
const TEXT_SPACING = `* {
  line-height: 1.5 !important;
  letter-spacing: 0.12em !important;
  word-spacing: 0.16em !important;
}
p { margin-bottom: 2em !important; }`

/** How far the page scrolls sideways with `css` applied */
const overflowWith = (page, css) => page.evaluate(css => {
  // A constructed stylesheet: the CSP refuses a <style> element
  const sheet = new CSSStyleSheet()
  sheet.replaceSync(css)
  document.adoptedStyleSheets = [sheet]
  const { scrollWidth, clientWidth } = document.documentElement
  document.adoptedStyleSheets = []
  return scrollWidth - clientWidth
}, css)

/**
 * Nothing scrolls sideways: WCAG 1.4.10 and 1.4.12 at 320px wide (400%
 * zoom), as it is and with the text-spacing overrides, and 1.4.4 with
 * text at 200% at the page's own width.
 */
export async function expectReflow(page) {
  expect(await overflowWith(page, 'html { font-size: 200% !important; }'),
    'sideways scroll with text at 200%').toBeLessThanOrEqual(0)

  const viewport = page.viewportSize()
  await page.setViewportSize({ width: 320, height: 640 })
  expect(await overflowWith(page, ''), 'sideways scroll at 320px').toBeLessThanOrEqual(0)
  expect(await overflowWith(page, TEXT_SPACING),
    'sideways scroll at 320px with text spacing').toBeLessThanOrEqual(0)
  await page.setViewportSize(viewport)
}

/**
 * WCAG 2.4.7 and 2.4.11: Tab through the whole page; every stop shows a
 * focus outline and is not hidden under anything (the navbar, a dialog).
 */
export async function expectVisibleFocus(page) {
  // Stops are told apart by element, not by name: two links with the same
  // text (the navbar's and the footer's) are both checked
  await page.evaluate(() => {
    document.activeElement?.blur()
    window.focusStops = new WeakSet()
  })
  const seen = []
  let roundTrip = false
  for (let press = 0; press < 200 && !roundTrip; press++) {
    await page.keyboard.press('Tab')
    const stop = await page.evaluate(() => {
      const el = document.activeElement
      // Out of the page, or round to a stop already checked
      if (!el || el === document.body || window.focusStops.has(el)) return null
      window.focusStops.add(el)
      const { outlineStyle, outlineWidth } = getComputedStyle(el)
      const box = el.getBoundingClientRect()
      const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
      return {
        name: `${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute('aria-label') || el.id).trim()}"`,
        outlined: outlineStyle !== 'none' && parseFloat(outlineWidth) > 0,
        uncovered: el === hit || el.contains(hit),
      }
    })
    roundTrip = stop === null
    if (!roundTrip) {
      seen.push(stop.name)
      expect(stop, `focus on ${stop.name}`).toEqual({ ...stop, outlined: true, uncovered: true })
    }
  }
  expect(seen.length, 'Tab reached the page\'s controls').toBeGreaterThan(0)
  expect(roundTrip, 'Tab went round the page within 200 stops').toBe(true)
}

/**
 * WCAG 2.5.8: every control is at least 24 by 24 px, except a link inside
 * a sentence, which the rule exempts.
 */
export async function expectTargetSize(page) {
  const small = await page.evaluate(() => [
    ...document.querySelectorAll('a[href], button, input, textarea, select'),
  ]
    // A link in running text (a paragraph, an address, or a label such as
    // the terms checkbox's) is exempt (SC 2.5.8's inline exception)
    .filter(el => el.checkVisibility() && !el.closest('p, address, label'))
    .map(el => ({ el, box: el.getBoundingClientRect() }))
    .filter(({ box }) => box.width < 24 || box.height < 24)
    .map(({ el, box }) => `${el.outerHTML.slice(0, 80)} is ${box.width}x${box.height}`))
  expect(small).toEqual([])
}

/**
 * Fail each test in the calling describe block if the page's CSP (nginx)
 * blocked anything: the CSP allows only the app's own files.
 */
export function expectNoCspViolations(test) {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.cspViolations = []
      document.addEventListener('securitypolicyviolation', event => {
        window.cspViolations.push(`${event.violatedDirective} ${event.blockedURI}`)
      })
    })
  })

  test.afterEach(async ({ page }) => {
    expect(await page.evaluate(() => window.cspViolations)).toEqual([])
  })
}
