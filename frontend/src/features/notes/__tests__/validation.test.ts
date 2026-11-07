import { describe, it, expect } from 'vitest'
import { backendConstant } from '@/test/backend'
import { validateNoteContent, NOTE_MAX_LENGTH } from '../validation'

describe('validateNoteContent', () => {
  it.each([
    ['one character', 'a'],
    ['the maximum length', 'a'.repeat(NOTE_MAX_LENGTH)],
    ['special characters and numbers', 'Note 123 with @#$% chars!'],
    ['letters, punctuation and symbols of any language', 'Grüße — 日本 €5 × 2'],
    // The backend trims too, so surrounding space never counts
    ['surrounding whitespace', '  Valid note  '],
  ])('accepts %s', (_, content) => {
    expect(validateNoteContent(content)).toBeUndefined()
  })

  it.each(['', '   ', '\t\t', '\n\n', '  \n\t  '])(
    'requires some content (%o)',
    (content) => {
      expect(validateNoteContent(content)).toBe('Note content is required')
    }
  )

  it('rejects a note longer than the notes.content column', () => {
    expect(validateNoteContent('a'.repeat(NOTE_MAX_LENGTH + 1)))
      .toBe(`Note must be at most ${NOTE_MAX_LENGTH} characters`)
  })

  it.each(['🚀', '❤', '1⃣', '️', '‍', '©', '°', '𠀀', 'a\nb'])(
    'rejects a note with %o, as the backend does',
    (symbol) => {
      expect(validateNoteContent(`Note ${symbol}`))
        .toBe('Note must not contain emoji or other symbols like © or °')
    }
  )
})

// The backend's limit is the real one; this only spares the user a round trip
it('NOTE_MAX_LENGTH matches the backend', () => {
  expect(NOTE_MAX_LENGTH).toBe(backendConstant('notes/models.py', 'NOTE_MAX_LENGTH'))
})
