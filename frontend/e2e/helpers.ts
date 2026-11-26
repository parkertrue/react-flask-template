import { expect, request, type Locator, type Page, type Route, type test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { createHmac, randomUUID } from 'crypto'
import { readFileSync } from 'fs'
import path from 'path'
import { APP_NAME, TERMS_VERSION } from '../src/appInfo'
import type { DataExportResponse } from '../src/api/schemas'
import config from '../playwright.config'

// What the helpers below leave on the page's window
declare global {
  interface Window {
    focusStops: WeakSet<Element>
    cspViolations: string[]
  }
}

/** The first group `pattern` finds in `text`; throws if it finds none */
function capture(text: string, pattern: RegExp) {
  const value = pattern.exec(text)?.[1]
  if (value === undefined) throw new Error(`Nothing matches ${String(pattern)}`)
  return value
}

export const TEST_PASSWORD = 'a secure test passphrase'

// Every run registers fresh accounts, so emails must never repeat
// Long, with nothing to break at (no hyphen or dot), as a real address can
// be: every reflow check then sees one, which a page that does not wrap it
// pushes sideways at 320px. The part before the @ may hold 64 characters.
export const uniqueEmail = (prefix: string) =>
  `${(prefix + randomUUID()).replaceAll('-', '').slice(0, 64)}@example.com`

// The test stack's Mailpit, which catches every email the worker sends
// (docker-compose.test.yml)
const MAILPIT_API = 'http://127.0.0.1:8026/api/v1'

interface MailpitSearch {
  messages: { ID: string }[]
}

/** The one email to an address with this subject, once the worker has sent it */
export async function emailTo(address: string, subject: string) {
  const query = encodeURIComponent(`to:"${address}" subject:"${subject}"`)
  let found: MailpitSearch['messages'] = []
  await expect.poll(async () => {
    const response = await fetch(`${MAILPIT_API}/search?query=${query}`)
    found = (await response.json() as MailpitSearch).messages
    return found.length
  }, { message: `an email to ${address}: ${subject}`, timeout: 15000 }).toBe(1)
  const response = await fetch(`${MAILPIT_API}/message/${found[0]?.ID ?? ''}`)
  return await response.json() as { Subject: string; Text: string }
}

/** The link in the one email to an address with this subject */
export async function emailedLink(address: string, subject = `Finish signing up for ${APP_NAME}`) {
  return capture((await emailTo(address, subject)).Text, /(https:\/\/\S+)/)
}

/** The address the unsigned links name: long, with nothing to break at */
export const LINK_ADDRESS = 'someonewithalongaddressthathasnothingtobreakat@example.com'

// A token no server signed: its payload names LINK_ADDRESS, which the page
// shows, and the backend refuses it as invalid
const UNSIGNED_TOKEN = `${Buffer.from(JSON.stringify([LINK_ADDRESS, ''])).toString('base64url')}.aTime.aSignature`

/** A sign-up link no server signed, for pages that need not finish */
export const UNSIGNED_LINK = `/signup/complete#token=${UNSIGNED_TOKEN}`

/** A password reset link no server signed, for pages that need not finish */
export const UNSIGNED_RESET_LINK = `/password-reset/complete#token=${UNSIGNED_TOKEN}`

/** An email change's link to the new address, no server signed */
export const UNSIGNED_CHANGE_LINK = `/account/email/complete#token=${UNSIGNED_TOKEN}`

/** An email change's link to the old address, no server signed */
export const UNSIGNED_UNDO_LINK = `/account/email/undo#token=${UNSIGNED_TOKEN}`

/** Ask to move the account on the account page, without waiting; returns the dialog */
export async function askToChangeEmail(page: Page, email: string, password = TEST_PASSWORD) {
  await page.getByRole('button', { name: 'Change email' }).click()
  const dialog = page.getByRole('dialog', { name: 'Change your email?' })
  await dialog.getByLabel('New email').fill(email)
  await dialog.getByLabel('Password').fill(password)
  return dialog
}

/** Fill in the account page's password dialog, without submitting; returns the dialog */
export async function askToChangePassword(page: Page, newPassword: string, current = TEST_PASSWORD) {
  await page.getByRole('button', { name: 'Change password' }).click()
  const dialog = page.getByRole('dialog', { name: 'Change your password?' })
  await dialog.getByLabel('Current password').fill(current)
  await dialog.getByLabel('New password', { exact: true }).fill(newPassword)
  await dialog.getByLabel('Confirm new password').fill(newPassword)
  return dialog
}

/** The subject of a password reset's email */
export const RESET_SUBJECT = `Reset your ${APP_NAME} password`

/** Ask for a password reset link on its page, without waiting */
export async function requestReset(page: Page, email: string) {
  await page.getByLabel(/^email/i).fill(email)
  await page.getByRole('button', { name: /^send link$|sending link/i }).click()
}

/** Fill in and submit the emailed reset link's page, without waiting */
export async function fillReset(page: Page, password = TEST_PASSWORD) {
  await page.getByLabel('New password', { exact: true }).fill(password)
  await page.getByLabel('Confirm new password').fill(password)
  await page.getByRole('button', { name: /save password|saving/i }).click()
}

/** Ask for a sign-up link on the sign-up page, without waiting */
export async function requestLink(page: Page, email: string) {
  await page.getByLabel(/^email/i).fill(email)
  await page.getByRole('button', { name: /^continue$|sending link/i }).click()
}

/** Fill in and submit the emailed link's page, without waiting */
export async function fillRegistration(page: Page, password = TEST_PASSWORD) {
  await page.getByLabel(/^password$/i).fill(password)
  await page.getByLabel(/confirm password/i).fill(password)
  await page.getByRole('checkbox', { name: /^I accept the Terms/ }).check()
  await page.getByRole('button', { name: /create account|creating account/i }).click()
}

/**
 * A new account, made through the API as the pages make it (the link read
 * from Mailpit), from a client of its own, so its cookie stays out of the
 * page's
 */
export async function createAccount(email: string, password = TEST_PASSWORD) {
  const client = await request.newContext({ baseURL: config.use?.baseURL, ignoreHTTPSErrors: true })
  const asked = await client.post('/api/auth/register', { data: { email } })
  expect(asked.status()).toBe(202)
  const token = new URLSearchParams(new URL(await emailedLink(email)).hash.slice(1)).get('token')
  const made = await client.post('/api/auth/register/complete', {
    data: { token, password, terms_version: TERMS_VERSION },
  })
  expect(made.status()).toBe(200)
  await client.dispose()
}

/** Where a visible element sits on the page */
export async function boxOf(locator: Locator) {
  const box = await locator.boundingBox()
  if (!box) throw new Error(`${String(locator)} is not visible`)
  return box
}

/**
 * Sign up through the UI as a user does: ask for the link, open it from the
 * email, choose a password. Signed in, on the page signing up leads to.
 */
export async function register(page: Page, email: string, password = TEST_PASSWORD) {
  await page.goto('/signup')
  await requestLink(page, email)
  await expect(page.getByRole('heading', { level: 1, name: 'Check your inbox' })).toBeVisible()
  await page.goto(await emailedLink(email))
  await fillRegistration(page, password)
  await page.waitForURL(url => url.pathname !== '/signup/complete', { timeout: 15000 })
}

/** Log in from the login page and wait to be sent on from it */
export async function login(page: Page, email: string, password = TEST_PASSWORD) {
  await page.getByLabel(/email/i).fill(email)
  await page.getByLabel(/password/i).fill(password)
  const loginButton = page.getByRole('button', { name: /^log in$|logging in/i })
  await expect(loginButton).toBeEnabled()
  await Promise.all([
    page.waitForURL(url => url.pathname !== '/login', { timeout: 15000 }),
    loginButton.click(),
  ])
}

/** A new account, signed in on the page signing up leads to; returns its email */
export async function registerAndLogin(page: Page, prefix: string) {
  const email = uniqueEmail(prefix)
  await register(page, email)
  return email
}

/** Log this device out from the navbar; it lands on the home page */
export async function logout(page: Page) {
  // Exact: the account page also has "Log out all devices"
  await page.getByRole('button', { name: 'Log out', exact: true }).click()
  await expectHomeReached(page)
}

/** Open the account page from the navbar's email link, once it has loaded */
export async function openAccount(page: Page) {
  await page.getByRole('link', { name: /\(account\)$/ }).click()
  await expect(memberSince(page)).toBeVisible()
}

/** The account page's line once GET /api/account has answered */
export const memberSince = (page: Page) => page.getByText(/^Member since /)

/**
 * On the account page, download the account's data; returns the saved
 * file's name and what it holds
 */
export async function downloadData(page: Page) {
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download your data' }).click()
  const download = await downloading
  const data = JSON.parse(readFileSync(await download.path(), 'utf-8')) as DataExportResponse
  return { filename: download.suggestedFilename(), data }
}

/**
 * On the account page, ask to log out all devices; returns the dialog that
 * opens, for its Log out all devices button
 */
export async function askToLogoutAll(page: Page) {
  await page.getByRole('button', { name: 'Log out all devices' }).click()
  const dialog = page.getByRole('dialog', { name: 'Log out all devices?' })
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  return dialog
}

/** Sign every device out from the account page, reached by the navbar's email */
export async function logoutAllDevices(page: Page) {
  await page.getByRole('link', { name: /\(account\)$/ }).click()
  const dialog = await askToLogoutAll(page)
  await dialog.getByRole('button', { name: 'Log out all devices' }).click()
  await expectHomeReached(page)
}

/**
 * On the account page, ask to delete the account and type the password into
 * the dialog that opens; returns the dialog, for its Delete account button
 */
export async function askToDeleteAccount(page: Page, password = TEST_PASSWORD) {
  await page.getByRole('button', { name: 'Delete account' }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete your account?' })
  await expect(dialog.getByLabel('Password')).toBeFocused()
  await dialog.getByLabel('Password').fill(password)
  return dialog
}

// The URL alone can pass on a home page that is replaced at once (by /login,
// if the session ended before home rendered); its focused h1 cannot
async function expectHomeReached(page: Page) {
  await page.waitForURL(/\/$/)
  await expect(page.getByRole('heading', { level: 1, name: `Welcome to ${APP_NAME}` }))
    .toBeFocused()
}

// The E2E backend signs tokens with SECRET_KEY from .env.test, so a test can
// re-sign the page's own access token as already expired: exactly what the
// browser holds once the real 15-minute token lapses.
function signingKey() {
  const env = readFileSync(path.join(import.meta.dirname, '..', '..', '.env.test'), 'utf8')
  return capture(env, /^SECRET_KEY=(.*)$/m).trim()
}

/** Replace the page's access token with the same one, expired */
export async function expireAccessToken(page: Page) {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  if (!token) throw new Error('The page holds no access token')
  const [header = '', payload = ''] = token.split('.')
  const claims = JSON.parse(Buffer.from(payload, 'base64url').toString()) as Record<string, unknown>
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
export async function expectNoViolations(page: Page) {
  await expect(page.locator('h1')).toHaveCount(1)
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .options({ rules: { 'heading-order': { enabled: true } } })
    .analyze()
  // The rule ids and the offending markup, so a failure says what to fix
  expect(violations.map(v => ({ rule: v.id, nodes: v.nodes.map(n => n.html) }))).toEqual([])
}

/** What every outage answers with, nginx's 502/504 as much as the backend's 503 */
export const SERVICE_UNAVAILABLE_MESSAGE = capture(readFileSync(
  path.join(import.meta.dirname, '..', '..', 'backend/app/utils/errors.py'), 'utf8',
), /^SERVICE_UNAVAILABLE_MESSAGE = '(.+)'$/m)

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
export async function holdRequests(
  page: Page, method: string, url: string | RegExp, answer?: Parameters<Route['fulfill']>[0],
) {
  const { promise: released, resolve } = Promise.withResolvers<undefined>()
  await page.route(url, async route => {
    if (route.request().method() !== method) return route.fallback()
    await released
    return answer ? route.fulfill(answer) : route.fallback()
  })
  return () => resolve(undefined)
}

// The text-spacing overrides WCAG 1.4.12 says content must survive
const TEXT_SPACING = `* {
  line-height: 1.5 !important;
  letter-spacing: 0.12em !important;
  word-spacing: 0.16em !important;
}
p { margin-bottom: 2em !important; }`

/** How far the page, or an open dialog, scrolls sideways with `css` applied */
const overflowWith = (page: Page, css: string) => page.evaluate(css => {
  // A constructed stylesheet: the CSP refuses a <style> element
  const sheet = new CSSStyleSheet()
  sheet.replaceSync(css)
  document.adoptedStyleSheets = [sheet]
  // The page, and an open modal dialog, which sits in the top layer: what
  // overflows inside it never widens the page
  const widths = [document.documentElement, ...document.querySelectorAll('dialog[open]')]
    .map(element => element.scrollWidth - element.clientWidth)
  document.adoptedStyleSheets = []
  return Math.max(...widths)
}, css)

/**
 * The values of visible read-only fields that are cut off and appear in no
 * text of the page: a field cannot wrap, so a long address in one must be
 * shown in full somewhere else
 */
const cutOffReadOnlyValues = (page: Page) => page.evaluate(() => {
  const text = document.body.innerText
  return [...document.querySelectorAll<HTMLInputElement>('input[readonly]')]
    .filter(input => input.checkVisibility() && input.scrollWidth > input.clientWidth)
    .map(input => input.value)
    .filter(value => !text.includes(value))
})

/**
 * Nothing scrolls sideways, on the page or in an open dialog: WCAG 1.4.10
 * and 1.4.12 at 320px wide (400% zoom), as it is and with the text-spacing
 * overrides, and 1.4.4 with text at 200% at the page's own width. And no
 * read-only field hides the end of a value the page shows nowhere else.
 */
export async function expectReflow(page: Page) {
  expect(await cutOffReadOnlyValues(page), 'read-only values cut off and shown nowhere else').toEqual([])
  expect(await overflowWith(page, 'html { font-size: 200% !important; }'),
    'sideways scroll with text at 200%').toBeLessThanOrEqual(0)

  const viewport = page.viewportSize() ?? { width: 1280, height: 720 }
  await page.setViewportSize({ width: 320, height: 640 })
  expect(await overflowWith(page, ''), 'sideways scroll at 320px').toBeLessThanOrEqual(0)
  expect(await overflowWith(page, TEXT_SPACING),
    'sideways scroll at 320px with text spacing').toBeLessThanOrEqual(0)
  await page.setViewportSize(viewport)
}

/**
 * WCAG 2.4.7 and 2.4.11: Tab round the whole page, stopCount stops; every
 * stop shows a focus outline and is not hidden under anything (the navbar, a
 * dialog). The count catches a walk, or a page, that silently got shorter.
 */
export async function expectVisibleFocus(page: Page, stopCount: number) {
  // Stops are told apart by element, not by name: two links with the same
  // text (the navbar's and the footer's) are both checked
  await page.evaluate(() => {
    window.focusStops = new WeakSet()
  })
  const stops: { name: string; outlined: boolean; uncovered: boolean }[] = []
  let roundTrip = false
  // Tab starts from whatever had focus last, not from the top, so the walk
  // goes past the page's end (focus leaves it) and round again until it
  // reaches a stop already checked
  for (let press = 0; press < 200 && !roundTrip; press++) {
    await page.keyboard.press('Tab')
    const stop = await page.evaluate(() => {
      const el = document.activeElement
      if (!el || el === document.body) return 'outside'
      if (window.focusStops.has(el)) return 'repeat'
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
    roundTrip = stop === 'repeat'
    if (typeof stop === 'object') stops.push(stop)
  }
  expect(roundTrip, 'Tab went round the page within 200 presses').toBe(true)
  expect(stops.map(stop => stop.name), 'the page\'s Tab stops').toHaveLength(stopCount)
  expect(stops.filter(stop => !stop.outlined || !stop.uncovered), 'stops without a visible focus')
    .toEqual([])
}

/**
 * WCAG 2.5.8: every control is at least 24 by 24 px, except a link inside
 * a sentence, which the rule exempts.
 */
export async function expectTargetSize(page: Page) {
  const small = await page.evaluate(() => [
    ...document.querySelectorAll('a[href], button, input, textarea, select'),
  ]
    // A link in running text (a paragraph, an address, or a label such as
    // the terms checkbox's) is exempt (SC 2.5.8's inline exception), but
    // not one alone in its paragraph, which no sentence holds
    .filter(el => {
      const text = el.closest('p, address, label')
      const inSentence = text !== null && text.textContent.trim() !== el.textContent.trim()
      return el.checkVisibility() && !inSentence
    })
    .map(el => ({ el, box: el.getBoundingClientRect() }))
    .filter(({ box }) => box.width < 24 || box.height < 24)
    .map(({ el, box }) => `${el.outerHTML.slice(0, 80)} is ${box.width}x${box.height}`))
  expect(small).toEqual([])
}

/**
 * Fail each test in the calling describe block if the page's CSP (nginx)
 * blocked anything: the CSP allows only the app's own files.
 */
export function expectNoCspViolations(tests: typeof test) {
  tests.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.cspViolations = []
      document.addEventListener('securitypolicyviolation', event => {
        window.cspViolations.push(`${event.violatedDirective} ${event.blockedURI}`)
      })
    })
  })

  tests.afterEach(async ({ page }) => {
    expect(await page.evaluate(() => window.cspViolations)).toEqual([])
  })
}
