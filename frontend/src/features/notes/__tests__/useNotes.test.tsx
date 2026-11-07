import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, renderHook, screen, waitFor, act } from '@testing-library/react'
import { useNotes } from '../useNotes'
import { fetchNotes, createNote, updateNote, deleteNote, type Note, type NotesResponse } from '../notesService'
import { note } from './fixtures'
import { httpError } from '@/test/fixtures'
import { AuthProvider } from '@/auth/AuthProvider'
import { useAuth } from '@/auth/useAuth'
import { signIn } from '@/test/router'

vi.mock('../notesService')

const page = (notes: Note[], next_cursor: number | null = null): NotesResponse => ({ notes, next_cursor })

type Notes = ReturnType<typeof useNotes>

describe('useNotes', () => {
  const wrapper = ({ children }: { children: ReactNode }) => <AuthProvider>{children}</AuthProvider>

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
        note({ id: 1, content: 'Note 1' }),
        note({ id: 2, content: 'Note 2' })
      ]
      vi.mocked(fetchNotes).mockResolvedValue(page(mockNotes))

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
      const error = httpError(500, { error: { message: 'Failed to fetch' } })
      vi.mocked(fetchNotes).mockRejectedValue(error)

      const { result } = renderHook(() => useNotes(), { wrapper })

      await waitFor(() => {
        expect(result.current.loading).toBe(false)
      })

      expect(result.current.notes).toEqual([])
      expect(result.current.error).toBe('Failed to fetch')
    })

    it('should handle network error', async () => {
      vi.mocked(fetchNotes).mockRejectedValue(new Error('Network error'))

      const { result } = renderHook(() => useNotes(), { wrapper })

      await waitFor(() => {
        expect(result.current.error).toBe('Network error')
      })
    })
  })

  describe('addNote', () => {
    beforeEach(() => {
      signIn()
      vi.mocked(fetchNotes).mockResolvedValue(page([]))
    })

    it('should add note to list', async () => {
      const newNote = note({ id: 1, content: 'New note' })
      vi.mocked(createNote).mockResolvedValue(newNote)

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
      const existingNotes = [note({ id: 1, content: 'Existing' })]
      vi.mocked(fetchNotes).mockResolvedValue(page(existingNotes))

      const newNote = note({ id: 2, content: 'New note' })
      vi.mocked(createNote).mockResolvedValue(newNote)

      const { result } = renderHook(() => useNotes(), { wrapper })

      await waitFor(() => {
        expect(result.current.notes).toEqual(existingNotes)
      })

      await act(async () => {
        await result.current.addNote('New note')
      })

      expect(result.current.notes).toEqual([newNote, ...existingNotes])
    })

    it('puts it on the first page when several are loaded', async () => {
      vi.mocked(fetchNotes).mockResolvedValueOnce(page([note({ id: 5, content: 'Five' })], 5))
      vi.mocked(createNote).mockResolvedValue(note({ id: 6, content: 'Six' }))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))
      vi.mocked(fetchNotes).mockResolvedValueOnce(page([note({ id: 4, content: 'Four' })]))
      await act(async () => {
        await result.current.loadMore()
      })

      await act(async () => {
        await result.current.addNote('Six')
      })

      expect(result.current.notes.map(note => note.id)).toEqual([6, 5, 4])
    })

    it('should handle create error', async () => {
      const error = httpError(500, { error: { message: 'Failed to create' } })
      vi.mocked(createNote).mockRejectedValue(error)

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
    const loaded = [note({ id: 2, content: 'Two' }), note({ id: 1, content: 'One' })]

    async function renderLoaded() {
      vi.mocked(fetchNotes).mockResolvedValue(page(loaded, 1))
      const view = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(view.result.current.notes).toEqual(loaded))
      return view.result
    }

    beforeEach(() => {
      signIn()
    })

    it('editNote replaces the note in place', async () => {
      const edited = note({ id: 1, content: 'One, edited' })
      vi.mocked(updateNote).mockResolvedValue(edited)
      const result = await renderLoaded()

      await act(async () => {
        await result.current.editNote(1, 'One, edited')
      })

      expect(updateNote).toHaveBeenCalledWith(1, 'One, edited')
      expect(result.current.notes).toEqual([loaded[0], edited])
    })

    it('clears the status while the next action runs, so the same words are read again', async () => {
      vi.mocked(updateNote).mockResolvedValue(loaded[1] as Note)
      const result = await renderLoaded()
      await act(async () => {
        await result.current.editNote(1, 'One')
      })
      expect(result.current.status).toBe('Note saved')

      vi.mocked(updateNote).mockReturnValue(new Promise(() => {}))
      act(() => { void result.current.editNote(1, 'One') })

      expect(result.current.status).toBe('')
    })

    it('removeNote drops only that note and keeps the cursor', async () => {
      vi.mocked(deleteNote).mockResolvedValue()
      const result = await renderLoaded()

      await act(async () => {
        await result.current.removeNote(2)
      })

      expect(deleteNote).toHaveBeenCalledWith(2)
      expect(result.current.notes).toEqual([loaded[1]])
      expect(result.current.hasMore).toBe(true)
    })

    it.each([
      ['editNote', () => vi.mocked(updateNote).mockRejectedValue(new Error('Network error')),
        (current: Notes) => current.editNote(1, 'Changed')],
      ['removeNote', () => vi.mocked(deleteNote).mockRejectedValue(new Error('Network error')),
        (current: Notes) => current.removeNote(1)],
    ])('%s rethrows a failure for the row to show, leaving the notes and page error alone', async (_, fail, run) => {
      fail()
      const result = await renderLoaded()

      const thrown = await act(() => run(result.current).then(() => undefined, (err: unknown) => err))

      expect(thrown).toHaveProperty('message', 'Network error')
      expect(result.current.error).toBeNull()
      expect(result.current.notes).toEqual(loaded)
    })
  })

  describe('loadMore', () => {
    beforeEach(() => {
      signIn()
    })

    it('has more only while the last page returned a cursor', async () => {
      vi.mocked(fetchNotes).mockResolvedValueOnce(page([note({ id: 5, content: 'Five' })], 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      expect(result.current.hasMore).toBe(true)

      vi.mocked(fetchNotes).mockResolvedValueOnce(page([note({ id: 4, content: 'Four' })]))
      await act(async () => {
        await result.current.loadMore()
      })

      expect(result.current.hasMore).toBe(false)
    })

    it('fetches the next page with the cursor and appends it', async () => {
      const first = [note({ id: 5, content: 'Five' })]
      const second = [note({ id: 4, content: 'Four' })]
      vi.mocked(fetchNotes).mockResolvedValueOnce(page(first, 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      vi.mocked(fetchNotes).mockResolvedValueOnce(page(second))
      await act(async () => {
        await result.current.loadMore()
      })

      expect(fetchNotes).toHaveBeenLastCalledWith(5)
      expect(result.current.notes).toEqual([...first, ...second])
    })

    it('does nothing on the last page', async () => {
      vi.mocked(fetchNotes).mockResolvedValue(page([note({ id: 1, content: 'Only' })]))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      await act(async () => {
        await result.current.loadMore()
      })

      expect(fetchNotes).toHaveBeenCalledTimes(1)
    })

    it('sets loadingMore while the page is in flight', async () => {
      vi.mocked(fetchNotes).mockResolvedValueOnce(page([note({ id: 5, content: 'Five' })], 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      const { promise: resolvePagePromise, resolve: resolvePage } = Promise.withResolvers<NotesResponse>()
      vi.mocked(fetchNotes).mockReturnValueOnce(resolvePagePromise)
      let pending: Promise<void> | undefined
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
      vi.mocked(fetchNotes).mockResolvedValueOnce(page([note({ id: 5, content: 'Five' })], 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      vi.mocked(fetchNotes).mockReturnValueOnce(new Promise(() => {}))
      act(() => { void result.current.loadMore() })
      await act(async () => { await result.current.loadMore() })

      expect(fetchNotes).toHaveBeenCalledTimes(2)
    })

    it('keeps the loaded notes and shows an error when a page fails', async () => {
      const first = [note({ id: 5, content: 'Five' })]
      vi.mocked(fetchNotes).mockResolvedValueOnce(page(first, 5))
      const { result } = renderHook(() => useNotes(), { wrapper })
      await waitFor(() => expect(result.current.loading).toBe(false))

      vi.mocked(fetchNotes).mockRejectedValueOnce(new Error('Network error'))
      await act(async () => {
        await result.current.loadMore()
      })

      expect(result.current.notes).toEqual(first)
      expect(result.current.loaded).toBe(true)
      expect(result.current.error).toBe('Network error')
      expect(result.current.hasMore).toBe(true)
    })
  })

  describe('submitting', () => {
    beforeEach(() => {
      signIn()
      vi.mocked(fetchNotes).mockResolvedValue(page([]))
    })

    it('is true only while addNote is in flight, not during list loads', async () => {
      const { promise: resolveCreatePromise, resolve: resolveCreate } = Promise.withResolvers<Note>()
      vi.mocked(createNote).mockReturnValue(resolveCreatePromise)

      const { result } = renderHook(() => useNotes(), { wrapper })
      expect(result.current.loading).toBe(true)
      expect(result.current.submitting).toBe(false)
      await waitFor(() => expect(result.current.loading).toBe(false))

      let pending: Promise<void> | undefined
      act(() => { pending = result.current.addNote('New') })
      expect(result.current.submitting).toBe(true)
      expect(result.current.loading).toBe(false)

      await act(async () => {
        resolveCreate(note({ id: 1, content: 'New' }))
        await pending
      })
      expect(result.current.submitting).toBe(false)
    })

    it('resets after a failed add', async () => {
      vi.mocked(createNote).mockRejectedValue(new Error('Failed'))
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
      vi.mocked(fetchNotes).mockResolvedValue(page([note({ id: 1, content: 'Note' })], 1))

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

    it('leaves the list empty when an add finishes after logout', async () => {
      signIn()
      vi.mocked(fetchNotes).mockResolvedValue(page([note({ id: 1, content: 'Note' })]))
      const { promise: resolveCreatePromise, resolve: resolveCreate } = Promise.withResolvers<Note>()
      vi.mocked(createNote).mockReturnValue(resolveCreatePromise)
      const { result } = renderHook(
        () => ({ notes: useNotes(), auth: useAuth() }),
        { wrapper }
      )
      await waitFor(() => expect(result.current.notes.notes).toHaveLength(1))

      let pending: Promise<void> | undefined
      act(() => { pending = result.current.notes.addNote('Late') })
      act(() => result.current.auth.logout())
      await act(async () => {
        resolveCreate(note({ id: 2, content: 'Late' }))
        await pending
      })

      expect(result.current.notes.notes).toEqual([])
      expect(result.current.notes.error).toBeNull()
    })
  })

  describe('coming back to the list', () => {
    // Notes stands in for the page: shown, then left, then shown again
    function Notes() {
      const { notes } = useNotes()
      return <p>{notes.map(note => note.content).join(', ')}</p>
    }
    const Page = ({ shown }: { shown: boolean }) => <AuthProvider>{shown && <Notes />}</AuthProvider>

    it('shows the notes it had at once, while it fetches them again', async () => {
      signIn()
      vi.mocked(fetchNotes).mockResolvedValueOnce(page([note({ id: 1, content: 'Cached' })]))
      const { rerender } = render(<Page shown />)
      await screen.findByText('Cached')
      rerender(<Page shown={false} />)

      vi.mocked(fetchNotes).mockReturnValueOnce(new Promise(() => {}))
      rerender(<Page shown />)

      expect(screen.getByText('Cached')).toBeInTheDocument()
      expect(fetchNotes).toHaveBeenCalledTimes(2)
    })
  })
})
