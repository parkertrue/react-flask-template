import { useState, useEffect, useCallback } from 'react'
import { getErrorMessage } from '@/api/errors'
import { useAuth } from '@/auth/useAuth'
import { fetchNotes, createNote, updateNote, deleteNote } from './notesService'

// A failed request as an Error whose message is ready to show
const failure = err => new Error(getErrorMessage(err), { cause: err })

export function useNotes() {
  const { isAuthenticated } = useAuth()
  const [notes, setNotes] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  // Whether the first page has arrived, so a failed load never claims the
  // user has no notes
  const [loaded, setLoaded] = useState(false)
  // What the last add, save, delete or Load more did, for screen readers,
  // or that the first load is running. Cleared when the next one starts, so
  // the same words are read again.
  const [status, setStatus] = useState('')

  const loadNotes = useCallback(async () => {
    setLoading(true)
    setError(null)
    setStatus('Loading notes...')

    try {
      const page = await fetchNotes()
      setNotes(page.notes)
      setNextCursor(page.next_cursor)
      setLoaded(true)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
      setStatus('')
    }
  }, [])

  useEffect(() => {
    if (!isAuthenticated) return

    // Fetching on login is what this effect is for; the loading flag that
    // loadNotes sets before its first await is the one extra render we want.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadNotes()
    // Drop this session's notes when it ends, so the next user never sees them
    return () => {
      setNotes([])
      setNextCursor(null)
      setLoaded(false)
      setStatus('')
    }
  }, [isAuthenticated, loadNotes])

  const loadMore = async () => {
    if (nextCursor === null || loadingMore) return
    setLoadingMore(true)
    setStatus('')
    try {
      const page = await fetchNotes(nextCursor)
      setNotes(prev => [...prev, ...page.notes])
      setNextCursor(page.next_cursor)
      setError(null)
      setStatus(page.next_cursor === null ? 'All notes loaded' : 'More notes loaded')
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoadingMore(false)
    }
  }

  const addNote = async (content) => {
    setSubmitting(true)
    setStatus('')
    try {
      const newNote = await createNote(content)
      // Newest first. The cursor points below the oldest loaded note, so the
      // new one never turns up again on a later page.
      setNotes(prev => [newNote, ...prev])
      setError(null)
      setStatus('Note added')
    } catch (err) {
      const failed = failure(err)
      setError(failed.message)
      throw failed
    } finally {
      setSubmitting(false)
    }
  }

  // The note's row tracks its own busy state and shows its own error, so
  // these only apply the result, and rethrow a failure for the row to show
  const editNote = async (id, content) => {
    setStatus('')
    try {
      const updated = await updateNote(id, content)
      setNotes(prev => prev.map(note => note.id === id ? updated : note))
      setStatus('Note saved')
    } catch (err) {
      throw failure(err)
    }
  }

  // The cursor is the oldest loaded note's id, which stays a valid "before"
  // even once that note is gone
  const removeNote = async (id) => {
    setStatus('')
    try {
      await deleteNote(id)
      setNotes(prev => prev.filter(note => note.id !== id))
      setStatus('Note deleted')
    } catch (err) {
      throw failure(err)
    }
  }

  return {
    notes,
    loading,
    loaded,
    loadingMore,
    hasMore: nextCursor !== null,
    submitting,
    error,
    status,
    loadMore,
    addNote,
    editNote,
    removeNote
  }
}
