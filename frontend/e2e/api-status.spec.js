import { test, expect } from '@playwright/test'
import { expectNoCspViolations, expectNoViolations, serviceUnavailable } from './helpers'

// tokens.css's --color-success and --color-danger, as computed styles report them
const GREEN = 'rgb(30, 134, 74)'
const RED = 'rgb(192, 57, 43)'

const dotColor = status => status.evaluate(el => getComputedStyle(el, '::before').backgroundColor)

// The home page's API-status demo (src/features/health): deleted with it
test.describe('API status', () => {
  expectNoCspViolations(test)

  test('a backend that is up shows ok with a green dot, centered in a box that fits it', async ({ page }) => {
    await page.goto('/')
    const status = page.getByRole('status')

    await expect(status).toHaveText('API status: ok')
    expect(await dotColor(status)).toBe(GREEN)
    const text = await status.boundingBox()
    const box = await status.locator('..').boundingBox()
    // As much room above the text as below it
    expect(Math.abs((text.y - box.y) - (box.y + box.height - text.y - text.height))).toBeLessThan(1)
    // Its own width, not the page column's
    expect(box.width).toBeLessThan(text.width + 40)
  })

  test('a backend that is down shows as an error with a red dot, with no violations', async ({ page }) => {
    await page.route('**/api/health', route => route.fulfill(serviceUnavailable))
    await page.goto('/')
    const status = page.getByRole('status')

    await expect(status).toHaveText('API status: error')
    expect(await dotColor(status)).toBe(RED)
    await expectNoViolations(page)
  })
})
