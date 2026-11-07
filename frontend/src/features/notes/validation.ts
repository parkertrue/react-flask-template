import { hasUnsupportedCharacters, UNSUPPORTED_CHARACTERS_MESSAGE } from '@/utils/validation'

export const NOTE_MAX_LENGTH = 256

/**
 * Non-blank, at most NOTE_MAX_LENGTH characters once trimmed, and free of
 * emoji and other symbols, as backend/app/notes/schemas.py allows
 */
export function validateNoteContent(content: string): string | undefined {
  const trimmed = content.trim()

  if (!trimmed) {
    return 'Note content is required'
  }

  if (trimmed.length > NOTE_MAX_LENGTH) {
    return `Note must be at most ${NOTE_MAX_LENGTH} characters`
  }

  if (hasUnsupportedCharacters(trimmed)) {
    return `Note ${UNSUPPORTED_CHARACTERS_MESSAGE}`
  }

  return undefined
}
