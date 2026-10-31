import { useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import ConfirmDialog from '@/components/dialogs/ConfirmDialog'
import NoteForm from './NoteForm'

// One note: Edit opens it in place (NoteForm), Delete asks first. Each row
// keeps its own busy state and error, so the rest of the list stays usable
// and a failure shows beside the note it belongs to.
export default function NoteItem({ note, onEdit, onDelete, emptiedFocusRef }) {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')
  const rowRef = useRef(null)
  const editButtonRef = useRef(null)
  const contentId = `note-${note.id}-content`

  // Moving focus is right only while the user is still at this row: focus
  // inside it, or dropped to the page because the focused control went away.
  // If they have moved on to another note meanwhile, leave them there.
  const focusIsHere = row =>
    row.contains(document.activeElement) || document.activeElement === document.body

  const stopEditing = () => {
    const returnFocus = focusIsHere(rowRef.current)
    flushSync(() => {
      setEditing(false)
      setError('')
    })
    if (returnFocus) editButtonRef.current.focus()
  }

  const handleSave = async (content) => {
    setSaving(true)
    setError('')
    try {
      await onEdit(note.id, content)
    } catch (err) {
      setError(err.message)
      // NoteForm keeps the text for another try
      throw err
    } finally {
      setSaving(false)
    }
    stopEditing()
  }

  const handleDelete = async () => {
    setConfirming(false)
    setError('')
    const row = rowRef.current
    const neighbor = row.nextElementSibling ?? row.previousElementSibling

    setDeleting(true)
    try {
      await onDelete(note.id)
    } catch (err) {
      setError(err.message)
      setDeleting(false)
      return
    }
    // This row is going: hand focus to the next note (or the previous one),
    // or to emptiedFocusRef once none is left, rather than lose it
    if (focusIsHere(row)) {
      (neighbor?.querySelector('button') ?? emptiedFocusRef.current).focus()
    }
  }

  const errorMessage = error && <p className="field-error note-error" role="alert">{error}</p>

  if (editing) {
    return (
      <li ref={rowRef} className="note-item">
        <NoteForm
          id={`note-${note.id}-input`}
          label="Edit note"
          submitLabel="Save"
          busyLabel="Saving..."
          initialContent={note.content}
          onSubmit={handleSave}
          onCancel={stopEditing}
          submitting={saving}
        />
        {errorMessage}
      </li>
    )
  }

  // Every row has an Edit and a Delete, named by their visible labels and
  // described by the note's text, which tells one row's from another's
  return (
    <li ref={rowRef} className="note-item">
      <span id={contentId} className="note-content">{note.content}</span>
      <span className="note-actions">
        <button
          ref={editButtonRef}
          type="button"
          className="btn btn-secondary btn-small"
          aria-describedby={contentId}
          aria-disabled={deleting}
          onClick={() => { if (!deleting) setEditing(true) }}
        >
          Edit
        </button>
        <button
          type="button"
          className="btn btn-danger btn-small"
          aria-describedby={contentId}
          aria-disabled={deleting}
          onClick={() => { if (!deleting) setConfirming(true) }}
        >
          {deleting ? 'Deleting...' : 'Delete'}
        </button>
      </span>
      {errorMessage}
      {confirming && (
        <ConfirmDialog
          title="Delete this note?"
          confirmLabel="Delete"
          onConfirm={handleDelete}
          onCancel={() => setConfirming(false)}
        >
          <p>&ldquo;{note.content}&rdquo;</p>
          <p>This cannot be undone.</p>
        </ConfirmDialog>
      )}
    </li>
  )
}
