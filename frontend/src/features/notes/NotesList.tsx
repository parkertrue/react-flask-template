import type { Ref, RefObject } from 'react'
import NoteItem from './NoteItem'
import type { Note } from './notesService'

interface NotesListProps {
  ref?: Ref<HTMLUListElement>
  notes: Note[]
  loading: boolean
  loaded: boolean
  onEdit: (id: number, content: string) => Promise<void>
  onDelete: (id: number) => Promise<void>
  emptiedFocusRef: RefObject<HTMLElement | null>
}

export default function NotesList({ ref, notes, loading, loaded, onEdit, onDelete, emptiedFocusRef }: NotesListProps) {
  // Not a live region: the page's status line announces the load
  if (loading) {
    return <p className="notes-loading">Loading notes...</p>
  }

  if (notes.length === 0) {
    // Before the first page arrives (or when it failed) the list is unknown
    return loaded ? <p className="notes-empty">No notes yet. Add your first note!</p> : null
  }

  return (
    <ul ref={ref} className="notes-list">
      {notes.map(note => (
        <NoteItem
          key={note.id}
          note={note}
          onEdit={onEdit}
          onDelete={onDelete}
          emptiedFocusRef={emptiedFocusRef}
        />
      ))}
    </ul>
  )
}
