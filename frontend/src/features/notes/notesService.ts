import { api } from '@/api/api'
import type {
  NoteCreateRequest, NoteResponse, NotesListQuery, NotesPageResponse, NoteUpdateRequest,
} from '@/api/schemas'

// A note as the API sends it; created_at is an ISO 8601 time in UTC
export type Note = NoteResponse

// One page of notes, newest first. Pass a page's next_cursor to fetch the
// page after it; next_cursor is null on the last page.
export type NotesResponse = NotesPageResponse

export async function fetchNotes(before?: number) {
  const response = await api.get<NotesResponse>('/notes', { params: { before } satisfies NotesListQuery })
  return response.data
}

export async function createNote(content: string) {
  const response = await api.post<Note>('/notes', { content } satisfies NoteCreateRequest)
  return response.data
}

export async function updateNote(id: number, content: string) {
  const response = await api.put<Note>(`/notes/${id}`, { content } satisfies NoteUpdateRequest)
  return response.data
}

export async function deleteNote(id: number) {
  await api.delete(`/notes/${id}`)
}
