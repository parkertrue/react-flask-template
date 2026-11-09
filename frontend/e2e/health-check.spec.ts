import { test, expect } from '@playwright/test'
import { APP_NAME } from '../src/appName'
import { uniqueEmail } from './helpers'

test.describe('System Health Check', () => {
  test('API health endpoint is accessible', async ({ page }) => {
    // Relative, so it follows baseURL
    const response = await page.goto('/api/health')

    expect(response?.status()).toBe(200)
    expect(await response?.json()).toEqual({ status: 'ok' })
  })

  test('frontend loads correctly', async ({ page }) => {
    await page.goto('/')

    await expect(page.getByRole('heading', { level: 1, name: `Welcome to ${APP_NAME}` })).toBeVisible({ timeout: 10000 })
  })

  test('can navigate to register page', async ({ page }) => {
    await page.goto('/register')

    await expect(page).toHaveURL(/\/register/)
    await expect(page.getByRole('heading', { name: /register/i })).toBeVisible()
  })

  test('registration API returns JSON through nginx', async ({ request }) => {
    const response = await request.post('/api/auth/register', {
      data: { email: uniqueEmail('api-test') },
    })

    expect(response.status()).toBe(202)
    expect(await response.json()).toEqual({ message: 'Check your inbox' })
  })
})
