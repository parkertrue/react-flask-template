import { useEffect, useId, useRef } from 'react'

// A question that needs an answer typed in (a password) before something that
// cannot be undone, on the browser's own modal <dialog>, like ConfirmDialog.
// Render it only while asking: it opens on its first field as it mounts and
// stays open, through a failed submit too, until the page stops rendering it.
// onSubmit gets the form's submit event; Cancel and Escape call onCancel,
// and do nothing while busy.
export default function FormDialog({ title, description, children, submitLabel, busy, onSubmit, onCancel }) {
  const dialogRef = useRef(null)
  const openerRef = useRef(null)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    const dialog = dialogRef.current
    // Strict Mode runs this twice, and showModal() throws on an open dialog
    if (!dialog.open) {
      openerRef.current = document.activeElement
      dialog.showModal()
    }
    dialog.querySelector('input, textarea, select').focus()
    // Once the dialog is gone the page is no longer inert, so focus can go
    // back to the button that asked
    return () => openerRef.current?.focus()
  }, [])

  const cancel = () => {
    if (!busy) onCancel()
  }

  // Escape: the page decides when the dialog goes, by no longer rendering it
  const handleCancel = (e) => {
    e.preventDefault()
    cancel()
  }

  // A browser may close the dialog anyway, on a repeated Escape with no click
  // or key press in between. Mid-request it opens again, to show the outcome.
  const handleClose = () => {
    if (busy) dialogRef.current.showModal()
    else onCancel()
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!busy) onSubmit(e)
  }

  return (
    <dialog
      ref={dialogRef}
      className="dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={handleCancel}
      onClose={handleClose}
    >
      <h2 id={titleId}>{title}</h2>
      <form onSubmit={handleSubmit} noValidate>
        <div className="dialog-body">
          <p id={descriptionId}>{description}</p>
          {children}
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" aria-disabled={busy} onClick={cancel}>
            Cancel
          </button>
          <button type="submit" className="btn btn-danger" aria-disabled={busy}>
            {submitLabel}
          </button>
        </div>
      </form>
    </dialog>
  )
}
