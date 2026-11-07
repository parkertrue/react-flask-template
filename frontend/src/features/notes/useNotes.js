import { useState } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '@/api/errors'
import { useAuth } from '@/auth/useAuth'
import { fetchNotes, createNote, updateNote, deleteNote } from './notesService'

const NOTES = ['notes']

// A failed request as an Error whose message is ready to show
const failure = err => new Error(getErrorMessage(err), { cause: err })

// Applies a change to every loaded page. A cache emptied in the meantime (the
// session ended) stays empty: returning undefined leaves it alone.
const updatePages = (update) => data => data && {
  ...data,
  pages: data.pages.map((page, index) => ({ ...page, notes: update(page.notes, index) })),
}

export function useNotes() {
  const { isAuthenticated } = useAuth()
  const queryClient = useQueryClient()
  // Pages of notes, newest first. Each page's next_cursor fetches the next;
  // it is null on the last page, which ends the list.
  const query = useInfiniteQuery({
    queryKey: NOTES,
    queryFn: ({ pageParam }) => fetchNotes(pageParam),
    initialPageParam: undefined,
    getNextPageParam: lastPage => lastPage.next_cursor,
    enabled: isAuthenticated,
  })
  // Kept here, not by useMutation, whose flag clears on its own schedule: the
  // form must leave its busy state in the same render that empties it, or
  // what the user types in between is wiped
  const [submitting, setSubmitting] = useState(false)
  // The last add's or Load more's failure; a failed first load is the query's
  const [error, setError] = useState(null)
  // What the last add, save, delete or Load more did, for screen readers.
  // Cleared when the next one starts, so the same words are read again.
  const [status, setStatus] = useState('')

  const loadMore = async () => {
    if (!query.hasNextPage || query.isFetchingNextPage) return
    setStatus('')
    try {
      const result = await query.fetchNextPage({ throwOnError: true })
      setError(null)
      setStatus(result.hasNextPage ? 'More notes loaded' : 'All notes loaded')
    } catch (err) {
      setError(getErrorMessage(err))
    }
  }

  const addNote = async (content) => {
    setSubmitting(true)
    setStatus('')
    try {
      const newNote = await createNote(content)
      // Newest first. The cursor points below the oldest loaded note, so the
      // new one never turns up again on a later page.
      queryClient.setQueryData(NOTES, updatePages((notes, index) =>
        index === 0 ? [newNote, ...notes] : notes))
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
      queryClient.setQueryData(NOTES, updatePages(notes =>
        notes.map(note => note.id === id ? updated : note)))
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
      queryClient.setQueryData(NOTES, updatePages(notes =>
        notes.filter(note => note.id !== id)))
      setStatus('Note deleted')
    } catch (err) {
      throw failure(err)
    }
  }

  return {
    notes: query.data?.pages.flatMap(page => page.notes) ?? [],
    // The first page only; a refetch in the background keeps the list shown
    loading: query.isLoading,
    // Whether a page has arrived, so a failed load never claims the user has
    // no notes
    loaded: query.data !== undefined,
    loadingMore: query.isFetchingNextPage,
    hasMore: query.hasNextPage,
    submitting,
    error: query.isLoadingError ? getErrorMessage(query.error) : error,
    status: query.isLoading ? 'Loading notes...' : status,
    loadMore,
    addNote,
    editNote,
    removeNote
  }
}
