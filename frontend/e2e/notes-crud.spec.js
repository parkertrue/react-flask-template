import { test, expect } from '@playwright/test'
import {
  expectNoCspViolations, expectNoViolations, expectReflow, expectTargetSize,
  expectVisibleFocus, holdRequests, logout, registerAndLogin, serviceUnavailable,
} from './helpers'
import { APP_NAME } from '../src/appName.js'

/** The note field, found by its label as a screen reader finds it */
const noteInput = page => page.getByLabel('New note')

/** Add a note through the form and wait for it to be listed */
async function addNote(page, text) {
  await noteInput(page).fill(text)
  await page.getByRole('button', { name: 'Add note' }).click()
  await expect(page.getByText(text)).toBeVisible()
}

/** The notes page's message when the list loaded and is empty */
const noNotesYet = page => page.getByText(/no notes yet/i)

test.describe('Notes CRUD Operations', () => {
  // A fresh account and page per test, so each one runs (and retries) alone
  test.beforeEach(async ({ page }) => {
    await registerAndLogin(page, 'e2e-crud')
    await page.goto('/notes')
  })

  test('can create multiple notes', async ({ page }) => {
    for (const noteText of ['First note', 'Second note', 'Third note']) {
      await addNote(page, noteText)
    }
    await expect(page.getByRole('listitem')).toHaveCount(3)
  })

  test('can update a note', async ({ page }) => {
    await addNote(page, 'Original note text')

    await page.getByRole('button', { name: /^Edit note #/ }).click()
    const field = page.getByRole('textbox', { name: /^Edit note #/ })
    await expect(field).toBeFocused()
    await expect(field).toHaveValue('Original note text')
    await field.fill('Updated note text')
    await page.getByRole('button', { name: 'Save' }).click()

    await expect(page.getByText('Updated note text')).toBeVisible()
    await expect(page.getByText('Original note text')).toBeHidden()

    // Saved by the server, not only on screen
    await page.reload()
    await expect(page.getByText('Updated note text')).toBeVisible()
  })

  test('can delete a note', async ({ page }) => {
    await addNote(page, 'Note to keep')
    await addNote(page, 'Note to be deleted')

    const row = page.getByRole('listitem').filter({ hasText: 'Note to be deleted' })
    const deleteButton = row.getByRole('button', { name: /^Delete note #/ })
    const dialog = page.getByRole('dialog', { name: 'Delete this note?' })

    await deleteButton.click()
    await dialog.getByRole('button', { name: 'Delete' }).click()

    // The row, not the text: the closing dialog quotes the note too
    await expect(row).toHaveCount(0)
    // Focus moved to the remaining note rather than being lost
    await expect(page.getByRole('button', { name: /^Edit note #/ })).toBeFocused()

    await page.reload()
    await expect(page.getByRole('listitem')).toHaveCount(1)
    await expect(page.getByText('Note to keep')).toBeVisible()
  })

  test('empty note submission shows validation', async ({ page }) => {
    await page.getByRole('button', { name: 'Add note' }).click()

    // Explained on the field, which gets focus so a screen reader reads it
    await expect(noteInput(page)).toHaveAccessibleDescription(
      'Note content is required 256 characters remaining')
    await expect(noteInput(page)).toBeFocused()
  })

  test('notes persist across page reloads', async ({ page }) => {
    const persistentNote = `Persistent note ${Date.now()}`
    await addNote(page, persistentNote)

    await page.reload()

    await expect(page.getByText(persistentNote)).toBeVisible()
  })

  test('notes are private to user', async ({ page }) => {
    const firstUserNote = `Private note ${Date.now()}`
    await addNote(page, firstUserNote)

    await logout(page)
    await registerAndLogin(page, 'second-user')
    await page.goto('/notes')

    // The second user's list has loaded, and the first user's note is not in it
    await expect(noNotesYet(page)).toBeVisible()
    await expect(page.getByText(firstUserNote)).toBeHidden()
  })

  test('older notes load a page at a time', async ({ page }) => {
    // 21 notes, one more than a page, created through the API for speed
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    for (let i = 1; i <= 21; i++) {
      const response = await page.request.post('/api/notes', {
        data: { content: `Note number ${i}` },
        headers: { Authorization: `Bearer ${token}` },
      })
      expect(response.status()).toBe(201)
    }

    await page.reload()

    // Newest first: the oldest note is on the second page
    await expect(page.getByRole('listitem')).toHaveCount(20)
    await expect(page.getByText('Note number 21', { exact: true })).toBeVisible()
    await expect(page.getByText('Note number 1', { exact: true })).toBeHidden()

    await page.getByRole('button', { name: 'Load more' }).click()

    await expect(page.getByRole('listitem')).toHaveCount(21)
    await expect(page.getByText('Note number 1', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Load more' })).toBeHidden()
  })
})

test.describe('Notes accessibility', () => {
  expectNoCspViolations(test)

  test.beforeEach(async ({ page }) => {
    await registerAndLogin(page, 'e2e-notes-a11y')
    await page.goto('/notes')
  })

  test('the notes page has no violations', async ({ page }) => {
    await addNote(page, 'A note to check')

    await expect(page).toHaveTitle(`My notes | ${APP_NAME}`)
    await expectNoViolations(page)
  })

  test('a note open for editing has no violations, reflows, shows focus and has large enough targets', async ({ page }) => {
    await addNote(page, 'A note to edit')
    await page.getByRole('button', { name: /^Edit note #/ }).click()

    await expect(page.getByRole('textbox', { name: /^Edit note #/ })).toBeFocused()
    await expectNoViolations(page)
    await expectReflow(page)
    await expectVisibleFocus(page)
    await expectTargetSize(page)
  })

  test('the delete confirmation has no violations, and Escape keeps the note', async ({ page }) => {
    await addNote(page, 'A note to delete')
    await page.getByRole('button', { name: /^Delete note #/ }).click()

    const dialog = page.getByRole('dialog', { name: 'Delete this note?' })
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
    await expectNoViolations(page)

    // Focus goes back to the button that asked
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(page.getByRole('button', { name: /^Delete note #/ })).toBeFocused()
  })

  test('the notes page reflows, shows focus and has large enough targets', async ({ page }) => {
    await addNote(page, 'A note to tab past')

    await expectReflow(page)
    await expectVisibleFocus(page)
    await expectTargetSize(page)
  })

  test('adding, busy and then failed, has no violations', async ({ page }) => {
    await expect(noNotesYet(page)).toBeVisible()
    const release = await holdRequests(page, 'POST', '**/api/notes', serviceUnavailable)
    await noteInput(page).fill('A note that fails')
    await page.getByRole('button', { name: 'Add note' }).click()

    await expect(page.getByRole('button', { name: 'Adding...' })).toBeVisible()
    await expectNoViolations(page)

    release()
    await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
    await expectNoViolations(page)
  })

  test('saving, busy and then failed, has no violations', async ({ page }) => {
    await addNote(page, 'A note to save')
    const release = await holdRequests(page, 'PUT', '**/api/notes/*', serviceUnavailable)
    await page.getByRole('button', { name: /^Edit note #/ }).click()
    await page.getByRole('textbox', { name: /^Edit note #/ }).fill('Changed')
    await page.getByRole('button', { name: 'Save' }).click()

    await expect(page.getByRole('button', { name: 'Saving...' })).toBeVisible()
    await expectNoViolations(page)

    release()
    await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
    await expectNoViolations(page)
  })

  test('deleting, busy and then failed, has no violations', async ({ page }) => {
    await addNote(page, 'A note to keep after all')
    const release = await holdRequests(page, 'DELETE', '**/api/notes/*', serviceUnavailable)
    await page.getByRole('button', { name: /^Delete note #/ }).click()
    await page.getByRole('dialog', { name: 'Delete this note?' })
      .getByRole('button', { name: 'Delete' }).click()

    await expect(page.getByRole('button', { name: /^Deleting note #/ })).toBeVisible()
    await expectNoViolations(page)

    release()
    await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
    await expectNoViolations(page)
  })
})

test.describe('Notes accessibility, with the list answered by the test', () => {
  expectNoCspViolations(test)

  test.beforeEach(async ({ page }) => {
    await registerAndLogin(page, 'e2e-notes-a11y-list')
  })

  test('a failed load has no violations, and does not claim there are no notes', async ({ page }) => {
    await page.route('**/api/notes', route => route.fulfill(serviceUnavailable))
    await page.goto('/notes')

    await expect(page.getByRole('alert')).toHaveText(/temporarily unavailable/)
    await expect(noNotesYet(page)).toBeHidden()
    await expectNoViolations(page)
  })

  test('a full page with Load more, then loading more, has no violations', async ({ page }) => {
    // A first page of 20 with more to come; the next page is held
    const notes = Array.from({ length: 20 }, (_, i) => ({
      id: 40 - i, content: `Listed note ${40 - i}`,
      created_at: '2026-01-01T12:00:00+00:00',
    }))
    await page.route('**/api/notes', route => route.request().method() === 'GET'
      ? route.fulfill({ json: { notes, next_cursor: 21 } })
      : route.fallback())
    const release = await holdRequests(page, 'GET', '**/api/notes?before=*', {
      json: { notes: [], next_cursor: null },
    })
    await page.goto('/notes')

    await expect(page.getByRole('listitem')).toHaveCount(20)
    await expectNoViolations(page)

    await page.getByRole('button', { name: 'Load more' }).click()
    await expect(page.getByRole('button', { name: 'Loading...' })).toBeFocused()
    await expectNoViolations(page)
    release()
  })
})
