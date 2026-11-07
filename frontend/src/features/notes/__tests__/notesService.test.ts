import { describe, it, expect, vi } from 'vitest'
import { fetchNotes, createNote, updateNote, deleteNote } from '../notesService'
import { api } from '@/api/api'
import { note, notesPage } from './fixtures'

vi.mock('@/api/api')

describe('notesService', () => {
  describe('fetchNotes', () => {
    it('should GET the first page without a cursor', async () => {
      const mockPage = notesPage([{ id: 2 }, { id: 1 }])
      vi.mocked(api.get).mockResolvedValue({ data: mockPage })

      const result = await fetchNotes()

      expect(api.get).toHaveBeenCalledWith('/notes', { params: { before: undefined } })
      expect(result).toEqual(mockPage)
    })

    it('should pass the cursor as ?before=', async () => {
      vi.mocked(api.get).mockResolvedValue({ data: notesPage() })

      await fetchNotes(42)

      expect(api.get).toHaveBeenCalledWith('/notes', { params: { before: 42 } })
    })

    it('should propagate errors from API', async () => {
      const error = new Error('Failed to fetch notes')
      vi.mocked(api.get).mockRejectedValue(error)

      await expect(fetchNotes()).rejects.toThrow('Failed to fetch notes')
    })
  })

  describe('createNote', () => {
    it('should call POST /notes with content', async () => {
      const mockNote = note({ content: 'New note' })
      vi.mocked(api.post).mockResolvedValue({ data: mockNote })

      const result = await createNote('New note')

      expect(api.post).toHaveBeenCalledWith('/notes', {
        content: 'New note'
      })
      expect(result).toEqual(mockNote)
    })

    it('should handle empty content', async () => {
      const mockNote = note({ content: '' })
      vi.mocked(api.post).mockResolvedValue({ data: mockNote })

      const result = await createNote('')

      expect(api.post).toHaveBeenCalledWith('/notes', { content: '' })
      expect(result).toEqual(mockNote)
    })

    it('should propagate errors from API', async () => {
      const error = new Error('Failed to create note')
      vi.mocked(api.post).mockRejectedValue(error)

      await expect(createNote('Test note')).rejects.toThrow('Failed to create note')
    })
  })

  describe('updateNote', () => {
    it('should PUT the new content to /notes/:id', async () => {
      const mockNote = note({ id: 7, content: 'Edited' })
      vi.mocked(api.put).mockResolvedValue({ data: mockNote })

      const result = await updateNote(7, 'Edited')

      expect(api.put).toHaveBeenCalledWith('/notes/7', { content: 'Edited' })
      expect(result).toEqual(mockNote)
    })

    it('should propagate errors from API', async () => {
      vi.mocked(api.put).mockRejectedValue(new Error('Failed to update note'))

      await expect(updateNote(7, 'Edited')).rejects.toThrow('Failed to update note')
    })
  })

  describe('deleteNote', () => {
    it('should DELETE /notes/:id', async () => {
      vi.mocked(api.delete).mockResolvedValue({ status: 204 })

      await expect(deleteNote(7)).resolves.toBeUndefined()

      expect(api.delete).toHaveBeenCalledWith('/notes/7')
    })

    it('should propagate errors from API', async () => {
      vi.mocked(api.delete).mockRejectedValue(new Error('Failed to delete note'))

      await expect(deleteNote(7)).rejects.toThrow('Failed to delete note')
    })
  })
})
