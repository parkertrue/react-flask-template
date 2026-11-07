import type { SubmitEvent, KeyboardEvent } from 'react'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import { validateNoteContent, NOTE_MAX_LENGTH } from './validation'

interface NoteFormProps {
  // Resolves once the note is saved, and rejects if it was not
  onSubmit: (content: string) => Promise<void>
  submitting: boolean
  id?: string
  label?: string
  submitLabel?: string
  busyLabel?: string
  initialContent?: string
  onCancel?: () => void
}

// Adds a note by default; NoteItem passes an id, labels, the note's content
// and onCancel to edit one in place
export default function NoteForm({
  onSubmit,
  submitting,
  id = 'note-input',
  label = 'New note',
  submitLabel = 'Add note',
  busyLabel = 'Adding...',
  initialContent = '',
  onCancel,
}: NoteFormProps) {
  const { values, errors, handleChange, validate, reset } = useFormFields({ content: initialContent })

  const handleSubmit = async (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (submitting) return
    if (!validate(e.currentTarget, { content: validateNoteContent(values.content) })) return

    try {
      await onSubmit(values.content.trim())
      reset()
    } catch {
      // The parent shows the error; keep the text so the user can retry
    }
  }

  // Escape anywhere in the edit form cancels it, as it would a dialog
  const handleKeyDown = (e: KeyboardEvent<HTMLFormElement>) => {
    if (e.key === 'Escape' && onCancel && !submitting) onCancel()
  }

  return (
    <form onSubmit={e => void handleSubmit(e)} onKeyDown={handleKeyDown} noValidate className="note-form">
      <FormField
        id={id}
        name="content"
        label={label}
        type="text"
        value={values.content}
        onChange={handleChange}
        maxLength={NOTE_MAX_LENGTH}
        placeholder="Write a note..."
        readOnly={submitting}
        // Only the edit form, which opens on request, takes focus at once
        autoFocus={!!onCancel}
        error={errors.content}
        // Read with the input, so a screen reader hears why typing stops
        hint={`${NOTE_MAX_LENGTH - values.content.length} characters remaining`}
      >
        <button type="submit" aria-disabled={submitting} className="btn btn-primary">
          {submitting ? busyLabel : submitLabel}
        </button>
        {onCancel && (
          <button
            type="button"
            aria-disabled={submitting}
            className="btn btn-secondary"
            onClick={() => { if (!submitting) onCancel() }}
          >
            Cancel
          </button>
        )}
      </FormField>
    </form>
  )
}
