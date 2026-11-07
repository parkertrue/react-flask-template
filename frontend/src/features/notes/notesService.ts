import { api } from '@/api/api'

// A note as the API sends it; created_at is an ISO 8601 time in UTC
export interface Note {
  id: number
  content: string
  created_at: string
}

// One page of notes, newest first. Pass a page's next_cursor to fetch the
// page after it; next_cursor is null on the last page.
export interface NotesResponse {
  notes: Note[]
  next_cursor: number | null
}

export async function fetchNotes(before?: number) {
  const response = await api.get<NotesResponse>('/notes', { params: { before } })
  return response.data
}

export async function createNote(content: string) {
  const response = await api.post<Note>('/notes', { content })
  return response.data
}

export async function updateNote(id: number, content: string) {
  const response = await api.put<Note>(`/notes/${id}`, { content })
  return response.data
}

export async function deleteNote(id: number) {
  await api.delete(`/notes/${id}`)
}
