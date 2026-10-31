import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import NotesPage from '../NotesPage'
import { fetchNotes, createNote, updateNote, deleteNote } from '../notesService'
import { NOTE_MAX_LENGTH } from '../validation'
import { listed, note, notesPage } from './fixtures'
import { errorBody } from '@/test/fixtures'
import { renderRoutes, signIn } from '@/test/router'
import { APP_NAME } from '@/appName'

vi.mock('../notesService')

// The page wires useNotes to the form, the list (with each note's Edit and
// Delete), the error and "Load more"; the hook's own state handling is tested
// in useNotes.test.jsx.
describe('NotesPage', () => {
  beforeEach(() => {
    fetchNotes.mockResolvedValue(notesPage())
  })

  function renderPage() {
    signIn()
    return renderRoutes([{ path: '/notes', element: <NotesPage /> }], '/notes').user
  }

  const failure = message => Object.assign(new Error('500'), {
    response: { status: 500, data: errorBody('INTERNAL_ERROR', message) },
  })
  const noNotesYet = () => screen.findByText(/no notes yet/i)
  const rowOf = element => screen.getAllByRole('listitem').find(row => row.contains(element))
  // The page's one status line, which says what the last action did
  const announced = () => screen.getByRole('status')

  async function addNote(user, text) {
    await user.type(screen.getByLabelText('New note'), text)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
  }

  it('shows a loading state, then the user\'s notes', async () => {
    fetchNotes.mockResolvedValue(notesPage([{ id: 2, content: 'Second' }, { id: 1, content: 'First' }]))
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: 'My notes' })).toBeInTheDocument()
    // getByRole fails on two live regions: the list's text is not one
    expect(announced()).toHaveTextContent('Loading notes...')
    expect(document.title).toBe(`My notes | ${APP_NAME}`)

    expect(await screen.findByText('Second')).toBeInTheDocument()
    expect(listed()).toHaveLength(2)
    expect(announced()).toBeEmptyDOMElement()
  })

  it('shows the empty state when there are no notes', async () => {
    renderPage()

    expect(await noNotesYet()).toBeInTheDocument()
  })

  it('leaves focus alone on arrival: only an opened edit form takes it', async () => {
    renderPage()
    await noNotesYet()

    expect(screen.getByLabelText('New note')).not.toHaveFocus()
  })

  it('announces why the notes could not be loaded, without claiming there are none', async () => {
    fetchNotes.mockRejectedValue(failure('Something went wrong'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
    expect(screen.queryByText(/no notes yet/i)).not.toBeInTheDocument()
  })

  describe('adding a note', () => {
    it('puts it at the top of the list, empties the field and announces it', async () => {
      fetchNotes.mockResolvedValue(notesPage([{ id: 1, content: 'Existing' }]))
      createNote.mockResolvedValue(note({ id: 2, content: 'Fresh' }))
      const user = renderPage()
      await screen.findByText('Existing')
      // Present, and silent, before anything happens: a live region must be
      // in the page before its text changes to be read
      expect(announced()).toBeEmptyDOMElement()

      await addNote(user, 'Fresh')

      expect(await screen.findByText('Fresh')).toBeInTheDocument()
      expect(createNote).toHaveBeenCalledWith('Fresh')
      expect(listed()[0]).toContain('Fresh')
      expect(screen.getByLabelText('New note')).toHaveValue('')
      expect(announced()).toHaveTextContent('Note added')
    })

    it('announces the error and keeps the text when saving fails', async () => {
      createNote.mockRejectedValue(failure('Could not save'))
      const user = renderPage()
      await noNotesYet()

      await addNote(user, 'Unsaved')

      expect(await screen.findByRole('alert')).toHaveTextContent('Could not save')
      expect(screen.getByLabelText('New note')).toHaveValue('Unsaved')
    })

    it('clears an earlier error once a note saves', async () => {
      createNote
        .mockRejectedValueOnce(failure('Could not save'))
        .mockResolvedValueOnce(note({ content: 'Unsaved' }))
      const user = renderPage()
      await noNotesYet()
      await addNote(user, 'Unsaved')
      await screen.findByRole('alert')

      await user.click(screen.getByRole('button', { name: 'Add note' }))

      expect(await screen.findByRole('listitem')).toHaveTextContent('Unsaved')
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('blocks a second add while saving, but not while the list loads', async () => {
      fetchNotes.mockReturnValue(new Promise(() => {}))
      let finish
      createNote.mockImplementation(() => new Promise(resolve => { finish = resolve }))
      const user = renderPage()

      // The list is still loading: the form stays usable
      expect(screen.getByLabelText('New note')).not.toHaveAttribute('readonly')

      await addNote(user, 'Slow')

      expect(screen.getByLabelText('New note')).toHaveAttribute('readonly')
      expect(screen.getByRole('button', { name: 'Adding...' })).toHaveAttribute('aria-disabled', 'true')

      finish(note({ content: 'Slow' }))
      expect(await screen.findByRole('button', { name: 'Add note' })).toBeInTheDocument()
      expect(screen.getByLabelText('New note')).not.toHaveAttribute('readonly')
    })
  })

  describe('Load more', () => {
    it('is not offered when everything fits on one page', async () => {
      fetchNotes.mockResolvedValue(notesPage([{ id: 1, content: 'Only note' }]))
      renderPage()

      await screen.findByText('Only note')
      expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
    })

    it('adds the last page below, then goes away, handing focus to the first new note', async () => {
      fetchNotes
        .mockResolvedValueOnce(notesPage([{ id: 2, content: 'Newer' }], 2))
        .mockResolvedValueOnce(notesPage([{ id: 1, content: 'Older' }]))
      const user = renderPage()

      await user.click(await screen.findByRole('button', { name: 'Load more' }))

      expect(await screen.findByText('Older')).toBeInTheDocument()
      expect(fetchNotes).toHaveBeenLastCalledWith(2)
      expect(listed()).toEqual(['Newer', 'Older'])
      expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Edit', description: 'Older' })).toHaveFocus()
      expect(announced()).toHaveTextContent('All notes loaded')
    })

    it('keeps focus on itself while more pages remain', async () => {
      fetchNotes
        .mockResolvedValueOnce(notesPage([{ id: 3, content: 'Newest' }], 3))
        .mockResolvedValueOnce(notesPage([{ id: 2, content: 'Middle' }], 2))
      const user = renderPage()

      await user.click(await screen.findByRole('button', { name: 'Load more' }))

      expect(await screen.findByText('Middle')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Load more' })).toHaveFocus()
      expect(announced()).toHaveTextContent('More notes loaded')
    })

    // The rest were deleted in another tab, say
    it.each([
      ['the last note', async () => {},
        () => screen.getByRole('button', { name: 'Edit', description: 'Only' })],
      ['the heading once no note is left', async user => {
        await user.click(screen.getByRole('button', { name: 'Delete', description: 'Only' }))
        await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }))
        await noNotesYet()
      }, () => screen.getByRole('heading', { level: 1, name: 'My notes' })],
    ])('hands focus to %s when the last page turns out empty', async (_, before, focused) => {
      fetchNotes
        .mockResolvedValueOnce(notesPage([{ id: 2, content: 'Only' }], 2))
        .mockResolvedValueOnce(notesPage([]))
      deleteNote.mockResolvedValue()
      const user = renderPage()
      await screen.findByText('Only')
      await before(user)

      await user.click(screen.getByRole('button', { name: 'Load more' }))

      expect(await screen.findByText('All notes loaded')).toBeInTheDocument()
      expect(focused()).toHaveFocus()
    })

    it('leaves focus where it is if the user moved on while the page loaded', async () => {
      let finish
      fetchNotes
        .mockResolvedValueOnce(notesPage([{ id: 2, content: 'Newer' }], 2))
        .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      const user = renderPage()

      await user.click(await screen.findByRole('button', { name: 'Load more' }))
      await user.click(screen.getByLabelText('New note'))
      await act(async () => finish(notesPage([{ id: 1, content: 'Older' }])))

      expect(screen.getByText('Older')).toBeInTheDocument()
      expect(screen.getByLabelText('New note')).toHaveFocus()
    })

    it('refuses another click while the next page loads', async () => {
      fetchNotes
        .mockResolvedValueOnce(notesPage([{ id: 2, content: 'Newer' }], 2))
        .mockReturnValueOnce(new Promise(() => {}))
      const user = renderPage()

      await user.click(await screen.findByRole('button', { name: 'Load more' }))
      await user.click(screen.getByRole('button', { name: 'Loading...' }))

      expect(screen.getByRole('button', { name: 'Loading...' })).toHaveAttribute('aria-disabled', 'true')
      expect(fetchNotes).toHaveBeenCalledTimes(2)
      expect(within(screen.getByRole('list')).getByText('Newer')).toBeInTheDocument()
    })
  })

  describe('editing a note', () => {
    // A row's buttons are told apart by the note's text, which describes them
    const editButton = text => screen.getByRole('button', { name: 'Edit', description: text })
    // The one note open for editing
    const editField = () => screen.getByRole('textbox', { name: 'Edit note' })

    async function startEditing(user, text) {
      const button = await screen.findByRole('button', { name: 'Edit', description: text })
      const row = rowOf(button)
      await user.click(button)
      return within(row).getByRole('textbox', { name: 'Edit note' })
    }

    beforeEach(() => {
      fetchNotes.mockResolvedValue(notesPage([{ id: 2, content: 'Second' }, { id: 1, content: 'First' }]))
    })

    it('opens the note in place, saves it, and returns focus to Edit', async () => {
      updateNote.mockResolvedValue(note({ id: 1, content: 'First, edited' }))
      const user = renderPage()

      const field = await startEditing(user, 'First')
      expect(field).toHaveValue('First')
      expect(field).toHaveFocus()

      await user.type(field, ', edited ')
      await user.click(screen.getByRole('button', { name: 'Save' }))

      expect(await screen.findByText('First, edited')).toBeInTheDocument()
      expect(updateNote).toHaveBeenCalledWith(1, 'First, edited')
      expect(screen.queryByRole('textbox', { name: 'Edit note' })).not.toBeInTheDocument()
      expect(editButton('First, edited')).toHaveFocus()
      expect(listed()).toEqual(['Second', 'First, edited'])
      expect(announced()).toHaveTextContent('Note saved')
    })

    it.each([
      ['the Cancel button', user => user.click(screen.getByRole('button', { name: 'Cancel' }))],
      ['Escape', user => user.keyboard('{Escape}')],
    ])('drops the change on %s and returns focus to Edit', async (_, cancel) => {
      const user = renderPage()
      await user.type(await startEditing(user, 'First'), ' changed')

      await cancel(user)

      expect(screen.queryByRole('textbox', { name: 'Edit note' })).not.toBeInTheDocument()
      expect(editButton('First')).toHaveFocus()
      expect(listed()).toEqual(['Second', 'First'])
      expect(updateNote).not.toHaveBeenCalled()
    })

    it('refuses an empty note, explaining why on the field', async () => {
      const user = renderPage()
      const field = await startEditing(user, 'First')

      await user.clear(field)
      await user.click(screen.getByRole('button', { name: 'Save' }))

      expect(field).toHaveAccessibleDescription(
        `Note content is required ${NOTE_MAX_LENGTH} characters remaining`)
      expect(field).toHaveFocus()
      expect(updateNote).not.toHaveBeenCalled()
    })

    it('announces a failed save in its row and keeps the edit open with the text', async () => {
      updateNote.mockRejectedValue(failure('Could not save'))
      const user = renderPage()
      await user.type(await startEditing(user, 'First'), ' changed')

      await user.click(screen.getByRole('button', { name: 'Save' }))

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent('Could not save')
      expect(rowOf(editField())).toContainElement(alert)
      expect(editField()).toHaveValue('First changed')
      expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-disabled', 'false')

      await user.keyboard('{Escape}')
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('leaves focus where it is if the user moved to another note while saving', async () => {
      let finish
      updateNote.mockImplementation(() => new Promise(resolve => { finish = resolve }))
      const user = renderPage()
      await startEditing(user, 'First')
      await user.click(screen.getByRole('button', { name: 'Save' }))

      const other = await startEditing(user, 'Second')
      await act(async () => finish(note({ id: 1, content: 'First' })))

      // Only the other note's edit is left open
      expect(screen.getAllByRole('textbox', { name: 'Edit note' })).toEqual([other])
      expect(other).toHaveFocus()
    })

    it('holds the edit open while saving: no second save, no cancel', async () => {
      updateNote.mockReturnValue(new Promise(() => {}))
      const user = renderPage()
      await startEditing(user, 'First')

      await user.click(screen.getByRole('button', { name: 'Save' }))
      await user.click(screen.getByRole('button', { name: 'Saving...' }))
      await user.click(screen.getByRole('button', { name: 'Cancel' }))
      await user.keyboard('{Escape}')

      expect(screen.getByRole('button', { name: 'Saving...' })).toHaveAttribute('aria-disabled', 'true')
      expect(screen.getByRole('button', { name: 'Cancel' })).toHaveAttribute('aria-disabled', 'true')
      expect(editField()).toHaveAttribute('readonly')
      expect(updateNote).toHaveBeenCalledTimes(1)
    })
  })

  describe('deleting a note', () => {
    const deleteButton = text => screen.getByRole('button', { name: 'Delete', description: text })
    const dialog = () => screen.getByRole('dialog', { name: 'Delete this note?' })

    async function confirmDelete(user, text) {
      await user.click(await screen.findByRole('button', { name: 'Delete', description: text }))
      await user.click(within(dialog()).getByRole('button', { name: 'Delete' }))
    }

    it('asks first, quoting the note, with focus on Cancel', async () => {
      fetchNotes.mockResolvedValue(notesPage([{ id: 1, content: 'Maybe' }]))
      const user = renderPage()

      await user.click(await screen.findByRole('button', { name: 'Delete', description: 'Maybe' }))

      expect(dialog()).toHaveAccessibleDescription('“Maybe” This cannot be undone.')
      expect(within(dialog()).getByRole('button', { name: 'Cancel' })).toHaveFocus()
      expect(deleteNote).not.toHaveBeenCalled()
    })

    it.each([
      ['Cancel', user => user.click(within(dialog()).getByRole('button', { name: 'Cancel' }))],
      ['Escape', user => user.keyboard('{Escape}')],
    ])('keeps the note on %s and returns focus to Delete', async (_, cancel) => {
      fetchNotes.mockResolvedValue(notesPage([{ id: 1, content: 'Kept' }]))
      const user = renderPage()
      await user.click(await screen.findByRole('button', { name: 'Delete', description: 'Kept' }))

      await cancel(user)

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(screen.getByText('Kept')).toBeInTheDocument()
      expect(deleteButton('Kept')).toHaveFocus()
      expect(deleteNote).not.toHaveBeenCalled()
    })

    it.each([
      ['the next note', 2, 'Note 1'],
      ['the previous note once the last row goes', 1, 'Note 2'],
    ])('removes it once confirmed and moves focus to %s', async (_, id, focused) => {
      fetchNotes.mockResolvedValue(notesPage([3, 2, 1].map(n => ({ id: n, content: `Note ${n}` }))))
      deleteNote.mockResolvedValue()
      const user = renderPage()

      await confirmDelete(user, `Note ${id}`)

      expect(screen.queryByText(`Note ${id}`)).not.toBeInTheDocument()
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(deleteNote).toHaveBeenCalledWith(id)
      expect(screen.getByRole('button', { name: 'Edit', description: focused })).toHaveFocus()
      expect(announced()).toHaveTextContent('Note deleted')
    })

    it('moves focus to the heading once no note is left', async () => {
      fetchNotes.mockResolvedValue(notesPage([{ id: 1, content: 'Only' }]))
      deleteNote.mockResolvedValue()
      const user = renderPage()

      await confirmDelete(user, 'Only')

      expect(await noNotesYet()).toBeInTheDocument()
      expect(screen.getByRole('heading', { level: 1, name: 'My notes' })).toHaveFocus()
    })

    it('announces a failure and keeps the note', async () => {
      fetchNotes.mockResolvedValue(notesPage([{ id: 1, content: 'Kept' }]))
      deleteNote.mockRejectedValue(failure('Could not delete'))
      const user = renderPage()

      await confirmDelete(user, 'Kept')

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent('Could not delete')
      expect(rowOf(screen.getByText('Kept'))).toContainElement(alert)
      expect(deleteButton('Kept')).toHaveAttribute('aria-disabled', 'false')
      expect(deleteButton('Kept')).toHaveFocus()
    })

    it('leaves focus where it is if the user moved to another note while deleting', async () => {
      fetchNotes.mockResolvedValue(notesPage([{ id: 2, content: 'Stays' }, { id: 1, content: 'Going' }]))
      let finish
      deleteNote.mockImplementation(() => new Promise(resolve => { finish = resolve }))
      const user = renderPage()

      await confirmDelete(user, 'Going')
      await user.click(screen.getByRole('button', { name: 'Edit', description: 'Stays' }))
      const other = screen.getByRole('textbox', { name: 'Edit note' })
      await act(async () => finish())

      expect(screen.queryByText('Going')).not.toBeInTheDocument()
      expect(other).toHaveFocus()
    })

    it('blocks asking again, and editing, while deleting', async () => {
      fetchNotes.mockResolvedValue(notesPage([{ id: 1, content: 'Going' }]))
      deleteNote.mockReturnValue(new Promise(() => {}))
      const user = renderPage()

      await confirmDelete(user, 'Going')
      const busy = screen.getByRole('button', { name: 'Deleting...', description: 'Going' })
      await user.click(busy)
      await user.click(screen.getByRole('button', { name: 'Edit', description: 'Going' }))

      expect(busy).toHaveAttribute('aria-disabled', 'true')
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Edit', description: 'Going' })).toHaveAttribute('aria-disabled', 'true')
      expect(screen.queryByRole('textbox', { name: 'Edit note' })).not.toBeInTheDocument()
      expect(deleteNote).toHaveBeenCalledTimes(1)
    })
  })
})
