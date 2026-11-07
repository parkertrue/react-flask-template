import { useState, type ChangeEvent } from 'react'
import { flushSync } from 'react-dom'

// A message for each field that has one, keyed by field id
export type FieldErrors<V> = Partial<Record<keyof V, string | undefined>>

// Each field's value: its text, or whether a checkbox is ticked. Written
// out, so { acceptTerms: false } holds a boolean, not the literal false.
export type FieldValues<V> = { [K in keyof V]: V[K] extends boolean ? boolean : string }

// Values and validation messages for a form of FormFields, keyed by field id
export function useFormFields<V extends Record<string, string | boolean>>(startingValues: V) {
  // V's own types are no wider than its fields'
  const initialValues = startingValues as FieldValues<V>
  const [values, setValues] = useState(initialValues)
  const [errors, setErrors] = useState<FieldErrors<V>>({})

  // Editing a field clears its message. A checkbox's value is whether it is
  // ticked.
  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const { name, type, value, checked } = e.target
    setValues(prev => ({ ...prev, [name]: type === 'checkbox' ? checked : value }))
    setErrors(prev => ({ ...prev, [name]: undefined }))
  }

  // Returns whether every field is valid. If not, shows the messages and
  // focuses the first invalid field, so a screen reader reads its message.
  const validate = (form: HTMLFormElement, fieldErrors: FieldErrors<V>) => {
    const firstInvalid = Object.keys(fieldErrors).find(name => fieldErrors[name])
    // Rendered before focusing, so the message is there to be read
    flushSync(() => setErrors(fieldErrors))
    if (!firstInvalid) return true
    // Every field is a FormField, whose id names its input
    const field = form.elements.namedItem(firstInvalid) as HTMLInputElement
    field.focus()
    return false
  }

  // Back to the starting values (or new ones), with no messages
  const reset = (nextValues: FieldValues<V> = initialValues) => {
    setValues(nextValues)
    setErrors({})
  }

  return { values, errors, handleChange, validate, reset }
}
