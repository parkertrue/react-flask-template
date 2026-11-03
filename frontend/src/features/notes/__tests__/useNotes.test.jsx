import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useNotes } from '../useNotes'
import { fetchNotes, createNote, updateNote, deleteNote } from '../notesService'
import { AuthProvider } from '@/auth/AuthProvider'
import { useAuth } from '@/auth/useAuth'
import { signIn } from '@/test/router'

vi.mock('../notesService')

const page = (notes, next_cursor = null) => ({ notes, next_cursor })

describe('useNotes', () => {
  const wrapper = ({ children }) => <AuthProvider>{children}</AuthProvider>

  describe('when not authenticated', () => {
    it('should initialize with empty notes', () => {
      const { result } = renderHook(() => useNotes(), { wrapper })

      expect(result.current.notes).toEqual([])
      expect(result.current.loading).toBe(false)
      expect(result.current.error).toBeNull()
    })

    it('should not fetch notes', async () => {
      renderHook(() => useNotes(), { wrapper })

      await waitFor(() => {
        expect(fetchNotes).not.toHaveBeenCalled()
      })
    })
  })

  describe('when authenticated', () => {
    beforeEach(() => {
      signIn()
    })

    it('should fetch notes on mount', async () => {
      const mockNotes = [
        { id: 1, content: 'Note 1' },
        { id: 2, content: 'Note 2' }
      ]
      fetchNotes.mockResolvedValue(page(mockNotes))

      const { result } = renderHook(() => useNotes(), { wrapper })

      expect(result.current.loading).toBe(true)
      expect(result.current.status).toBe('Loading notes...')

      await waitFor(() => {
        expect(result.current.loading).toBe(false)
      })

      expect(result.current.status).toBe('')
      expect(result.current.notes).toEqual(mockNotes)
      expect(result.current.error).toBeNull()
      expect(fetchNotes).toHaveBeenCalledTimes(1)
    })

    it('should handle fetch error', async () => {
      const error = {
        response: {
          data: {
            error: { message: 'Failed to fetch' }
          }
        }
      }
      fetchNotes.mockRejectedValue(error)

      const { result } = renderHook(() => useNotes(), { wrapper })

      await waitFor(() => {
        expect(result.current.loading).toBe(false)
      })

      expect(result.current.notes).toEqual([])
      expect(result.current.error).toBe('Failed to fetch')
    })

    it('should handle network error', async () => {
      fetchNotes.mockRejectedValue(new Error('Network error'))

      const { result } = renderHook(() => useNotes(), { wrapper })

      await waitFor(() => {
        expect(result.current.error).toBe('Network error')
      })
    })
  })

  describe('addNote', () => {
    beforeEach(() => {
      signIn()
      fetchNotes.mockResolvedValue(page([]))
    })

    it('should add note to list', async () => {
      const newNote = { id: 1, content: 'New note' }
      createNote.mockResolvedValue(newNote)

      const { result } = renderHook(() => useNotes(), { wrapper })

      await waitFor(() => {
        expect(result.current.loading).toBe(false)
      })

      await act(async () => {
        await result.current.addNote('New note')
      })

      expect(result.current.notes).toContainEqual(newNote)
      expect(createNote).toHaveBeenCalledWith('New note')
    })

    it('should put the new note first (newest first)', async () => {
      const existingNotes = [{ id: 1, content: 'Existing' }]
      fetchNotes.mockResolvedValue(page(existingNotes))

      const newNote = { id: 2, content: 'New note' }
      createNote.mockResolvedValue(newNote)

      const { result } = renderHook(() => useNotes(), { wrapper })

      await waitFor(() => {
        expect(result.current.notes).toEqual(existingNotes)
      })

      await act(async () => {
        await result.current.addNote('New note')
      })

      expect(result.current.notes).toEqual([newNote, ...existingNotes])
    })

    it('should handle create error', async () => {
      const error = {
        response: {
          data: {
            error: { message: 'Failed to create' }
          }
        }
      }
      createNote.mockRejectedValue(error)

      const { result } = renderHook(() => useNotes(), { wrapper })

      await waitFor(() => {
        expect(result.current.loading).toBe(false)
      })

      await act(() => expect(result.current.addNote('New note')).rejects.toThrow('Failed to create'))

      // Check error state after act completes
      expect(result.current.error).toBe('Failed to create')
      expect(result.current.notes).toEqual([])
    })
  })

  describe('editNote and removeNote', () => {
    const loaded = [{ id: 2, content: 'Two' }, { id: 1, content: 'One' }]

    async function renderLoaded() {
      fetchNotes.mockResolvedValue(page(loaded, 1))
      const view = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(view.result.current.notes).toEqual(loaded))
      return view.result
    }

    beforeEach(() => {
      signIn()
    })

    it('editNote replaces the note in place', async () => {
      const edited = { id: 1, content: 'One, edited' }
      updateNote.mockResolvedValue(edited)
      const result = await renderLoaded()

      await act(async () => {
        await result.current.editNote(1, 'One, edited')
      })

      expect(updateNote).toHaveBeenCalledWith(1, 'One, edited')
      expect(result.current.notes).toEqual([loaded[0], edited])
    })

    it('clears the status while the next action runs, so the same words are read again', async () => {
      updateNote.mockResolvedValue(loaded[1])
      const result = await renderLoaded()
      await act(async () => {
        await result.current.editNote(1, 'One')
      })
      expect(result.current.status).toBe('Note saved')

      updateNote.mockReturnValue(new Promise(() => {}))
      act(() => { result.current.editNote(1, 'One') })

      expect(result.current.status).toBe('')
    })

    it('removeNote drops only that note and keeps the cursor', async () => {
      deleteNote.mockResolvedValue()
      const result = await renderLoaded()

      await act(async () => {
        await result.current.removeNote(2)
      })

      expect(deleteNote).toHaveBeenCalledWith(2)
      expect(result.current.notes).toEqual([loaded[1]])
      expect(result.current.hasMore).toBe(true)
    })

    it.each([
      ['editNote', () => updateNote, current => current.editNote(1, 'Changed')],
      ['removeNote', () => deleteNote, current => current.removeNote(1)],
    ])('%s rethrows a failure for the row to show, leaving the notes and page error alone', async (_, service, run) => {
      service().mockRejectedValue(new Error('Network error'))
      const result = await renderLoaded()

      let thrown
      await act(async () => {
        await run(result.current).catch(err => { thrown = err })
      })

      expect(thrown.message).toBe('Network error')
      expect(result.current.error).toBeNull()
      expect(result.current.notes).toEqual(loaded)
    })
  })

  describe('loadMore', () => {
    beforeEach(() => {
      signIn()
    })

    it('has more only while the last page returned a cursor', async () => {
      fetchNotes.mockResolvedValueOnce(page([{ id: 5, content: 'Five' }], 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      expect(result.current.hasMore).toBe(true)

      fetchNotes.mockResolvedValueOnce(page([{ id: 4, content: 'Four' }]))
      await act(async () => {
        await result.current.loadMore()
      })

      expect(result.current.hasMore).toBe(false)
    })

    it('fetches the next page with the cursor and appends it', async () => {
      const first = [{ id: 5, content: 'Five' }]
      const second = [{ id: 4, content: 'Four' }]
      fetchNotes.mockResolvedValueOnce(page(first, 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      fetchNotes.mockResolvedValueOnce(page(second))
      await act(async () => {
        await result.current.loadMore()
      })

      expect(fetchNotes).toHaveBeenLastCalledWith(5)
      expect(result.current.notes).toEqual([...first, ...second])
    })

    it('does nothing on the last page', async () => {
      fetchNotes.mockResolvedValue(page([{ id: 1, content: 'Only' }]))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      await act(async () => {
        await result.current.loadMore()
      })

      expect(fetchNotes).toHaveBeenCalledTimes(1)
    })

    it('sets loadingMore while the page is in flight', async () => {
      fetchNotes.mockResolvedValueOnce(page([{ id: 5, content: 'Five' }], 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      let resolvePage
      fetchNotes.mockReturnValueOnce(new Promise(resolve => { resolvePage = resolve }))
      let pending
      act(() => { pending = result.current.loadMore() })
      expect(result.current.loadingMore).toBe(true)
      expect(result.current.loading).toBe(false)

      await act(async () => {
        resolvePage(page([]))
        await pending
      })
      expect(result.current.loadingMore).toBe(false)
    })

    it('ignores another call while a page is in flight', async () => {
      fetchNotes.mockResolvedValueOnce(page([{ id: 5, content: 'Five' }], 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      fetchNotes.mockReturnValueOnce(new Promise(() => {}))
      act(() => { result.current.loadMore() })
      await act(async () => { await result.current.loadMore() })

      expect(fetchNotes).toHaveBeenCalledTimes(2)
    })

    it('keeps the loaded notes and shows an error when a page fails', async () => {
      const first = [{ id: 5, content: 'Five' }]
      fetchNotes.mockResolvedValueOnce(page(first, 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      fetchNotes.mockRejectedValueOnce(new Error('Network error'))
      await act(async () => {
        await result.current.loadMore()
      })

      expect(result.current.notes).toEqual(first)
      expect(result.current.error).toBe('Network error')
      expect(result.current.hasMore).toBe(true)
    })
  })

  describe('submitting', () => {
    beforeEach(() => {
      signIn()
      fetchNotes.mockResolvedValue(page([]))
    })

    it('is true only while addNote is in flight, not during list loads', async () => {
      let resolveCreate
      createNote.mockReturnValue(new Promise(resolve => { resolveCreate = resolve }))

      const { result } = renderHook(() => useNotes(), { wrapper })
      expect(result.current.loading).toBe(true)
      expect(result.current.submitting).toBe(false)
      await waitFor(() => expect(result.current.loading).toBe(false))

      let pending
      act(() => { pending = result.current.addNote('New') })
      expect(result.current.submitting).toBe(true)
      expect(result.current.loading).toBe(false)

      await act(async () => {
        resolveCreate({ id: 1, content: 'New' })
        await pending
      })
      expect(result.current.submitting).toBe(false)
    })

    it('resets after a failed add', async () => {
      createNote.mockRejectedValue(new Error('Failed'))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      await act(async () => {
        await result.current.addNote('New').catch(() => {})
      })

      expect(result.current.submitting).toBe(false)
    })
  })

  describe('authentication changes', () => {
    it('should clear notes when logged out', async () => {
      signIn()
      fetchNotes.mockResolvedValue(page([{ id: 1, content: 'Note' }], 1))

      const { result } = renderHook(
        () => ({ notes: useNotes(), auth: useAuth() }),
        { wrapper }
      )

      await waitFor(() => {
        expect(result.current.notes.notes).toHaveLength(1)
      })

      act(() => result.current.auth.logout())

      expect(result.current.notes.notes).toEqual([])
      expect(result.current.notes.hasMore).toBe(false)
      expect(fetchNotes).toHaveBeenCalledTimes(1)
    })
  })
})
