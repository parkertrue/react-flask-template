import { describe, it, expect } from 'vitest'
import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { routes } from '@/routes'
import { errorBody } from '@/test/fixtures'
import { renderRoutes, signIn } from '@/test/router'
import { handlers, setupMswServer } from '@/test/server'
import { notesHandlers, notesPage } from './fixtures'

// The notes page against the real axios client, with the network faked at
// the HTTP layer, as test/integration/auth-flow.test.jsx does for auth
const server = setupMswServer(...handlers, ...notesHandlers)

describe('Notes, through the whole app', () => {
  it('creates a note and shows it', async () => {
    signIn()
    const { user } = renderRoutes(routes, '/notes')

    await screen.findByText(/no notes yet/i)
    await user.type(screen.getByLabelText('New note'), 'My new test note')
    await user.click(screen.getByRole('button', { name: 'Add note' }))

    expect(await screen.findByText('My new test note')).toBeInTheDocument()
  })

  it('edits a note, then deletes it', async () => {
    signIn()
    server.use(
      http.get('/api/notes', () =>
        HttpResponse.json(notesPage([{ id: 1, content: 'Draft' }])))
    )
    const { user } = renderRoutes(routes, '/notes')

    await user.click(await screen.findByRole('button', { name: 'Edit', description: 'Draft' }))
    const field = screen.getByRole('textbox', { name: 'Edit note' })
    await user.clear(field)
    await user.type(field, 'Final')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Final')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Delete', description: 'Final' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText(/no notes yet/i)).toBeInTheDocument()
  })

  it('shows the API\'s message when the note is already gone', async () => {
    signIn()
    server.use(
      http.get('/api/notes', () =>
        HttpResponse.json(notesPage([{ id: 1, content: 'Stale' }]))),
      http.delete('/api/notes/:id', () =>
        HttpResponse.json(errorBody('NOT_FOUND', 'Resource not found'), { status: 404 }))
    )
    const { user } = renderRoutes(routes, '/notes')

    await user.click(await screen.findByRole('button', { name: 'Delete', description: 'Stale' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Resource not found')
    expect(screen.getByText('Stale')).toBeInTheDocument()
  })

  it('shows the API\'s message at the notes cap, and keeps the typed note', async () => {
    signIn()
    const message = 'You can keep at most 1,000 notes. Delete one to add another.'
    server.use(
      http.post('/api/notes', () =>
        HttpResponse.json(errorBody('QUOTA_EXCEEDED', message), { status: 409 }))
    )
    const { user } = renderRoutes(routes, '/notes')

    await screen.findByText(/no notes yet/i)
    await user.type(screen.getByLabelText('New note'), 'One too many')
    await user.click(screen.getByRole('button', { name: 'Add note' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.getByLabelText('New note')).toHaveValue('One too many')
  })
})
