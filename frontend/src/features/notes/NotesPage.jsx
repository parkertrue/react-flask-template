import { useEffect, useRef } from 'react'
import PageTitle from '@/components/layout/PageTitle'
import { useNotes } from './useNotes'
import NotesList from './NotesList'
import NoteForm from './NoteForm'
import './notes.css'

export default function NotesPage() {
  const {
    notes, loading, loaded, loadingMore, hasMore, submitting, error, status,
    addNote, editNote, removeNote, loadMore
  } = useNotes()
  // Where focus goes when the last note is deleted
  const headingRef = useRef(null)
  const listRef = useRef(null)
  // Where the page Load more is fetching will start in the list
  const firstNewRef = useRef(null)

  const handleLoadMore = () => {
    if (loadingMore) return
    firstNewRef.current = notes.length
    loadMore()
  }

  // The last page takes Load more away, and focus with it: hand focus to the
  // first note that page brought in. Focus anywhere else means the user has
  // moved on, so leave it there.
  useEffect(() => {
    const firstNew = firstNewRef.current
    if (loadingMore || firstNew === null) return
    firstNewRef.current = null
    if (document.activeElement !== document.body) return

    const rows = listRef.current?.children ?? []
    const row = rows[firstNew] ?? rows[rows.length - 1]
    const target = row?.querySelector('button') ?? headingRef.current
    target.focus()
  }, [loadingMore])

  return (
    <div className="notes-page page-column">
      <PageTitle>My notes</PageTitle>
      <h1 ref={headingRef} tabIndex={-1}>My notes</h1>

      <NoteForm onSubmit={addNote} submitting={submitting} />

      {error && <div className="error-message" role="alert">{error}</div>}
      {/* Always rendered: a live region added along with its text is not read */}
      <p className="visually-hidden" role="status">{status}</p>

      <NotesList
        ref={listRef}
        notes={notes}
        loading={loading}
        loaded={loaded}
        onEdit={editNote}
        onDelete={removeNote}
        emptiedFocusRef={headingRef}
      />

      {hasMore && !loading && (
        <button
          type="button"
          className="btn btn-secondary btn-block load-more"
          onClick={handleLoadMore}
          aria-disabled={loadingMore}
        >
          {loadingMore ? 'Loading...' : 'Load more'}
        </button>
      )}
    </div>
  )
}
