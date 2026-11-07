import type { ComponentProps, ReactNode } from 'react'

type FormFieldProps = Omit<ComponentProps<'input'>, 'children'> & {
  id: string
  label: ReactNode
  error?: string | undefined
  hint?: string | undefined
  children?: ReactNode
}

// A labelled input with an optional hint and its validation message. The
// message marks the input invalid, and screen readers read it, then the
// hint, along with the label. Children (such as a form's buttons) sit on
// the input's line. The name defaults to the id, which must be unique on the
// page; pass a name when several forms hold the same field. A checkbox
// comes before its label, on one line, and takes no children.
export default function FormField({ id, name = id, label, error, hint, children, ...inputProps }: FormFieldProps) {
  const errorId = error ? `${id}-error` : undefined
  const hintId = hint ? `${id}-hint` : undefined
  const checkbox = inputProps.type === 'checkbox'

  const input = (
    <input
      id={id}
      name={name}
      className={checkbox ? 'form-checkbox' : 'form-input'}
      aria-invalid={!!error}
      aria-describedby={[errorId, hintId].filter(Boolean).join(' ') || undefined}
      {...inputProps}
    />
  )

  return (
    <div className="form-group">
      {checkbox ? (
        <div className="form-check">
          {input}
          <label htmlFor={id} className="form-label">{label}</label>
        </div>
      ) : (
        <>
          <label htmlFor={id} className="form-label">{label}</label>
          {children ? <div className="form-row">{input}{children}</div> : input}
        </>
      )}
      {hint && <p id={hintId} className="form-hint">{hint}</p>}
      {error && <p id={errorId} className="field-error">{error}</p>}
    </div>
  )
}
