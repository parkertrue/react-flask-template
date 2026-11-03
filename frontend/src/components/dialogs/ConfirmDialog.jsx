import { useEffect, useId, useRef } from 'react'

// A yes/no question on the browser's own modal <dialog>: showModal() keeps
// Tab inside it, makes the page behind it inert, and closes it on Escape.
// Render it only while asking; it opens as it mounts, and every way out
// (either button, Escape) ends in onConfirm or onCancel.
export default function ConfirmDialog({ title, children, confirmLabel, onConfirm, onCancel }) {
  const dialogRef = useRef(null)
  const cancelRef = useRef(null)
  const openerRef = useRef(null)
  const titleId = useId()
  const bodyId = useId()

  useEffect(() => {
    const dialog = dialogRef.current
    // Strict Mode runs this twice, and showModal() throws on an open dialog
    if (dialog.open) return
    openerRef.current = document.activeElement
    dialog.showModal()
    // Start on the answer that changes nothing
    cancelRef.current.focus()
  }, [])

  const handleClose = () => {
    // Browsers return focus to the opener on close; doing it here as well
    // covers any that do not
    openerRef.current?.focus()
    if (dialogRef.current.returnValue === 'confirm') onConfirm()
    else onCancel()
  }

  return (
    <dialog
      ref={dialogRef}
      className="dialog"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      onClose={handleClose}
    >
      <h2 id={titleId}>{title}</h2>
      <div id={bodyId} className="dialog-body">{children}</div>
      <div className="dialog-actions">
        <button
          ref={cancelRef}
          type="button"
          className="btn btn-secondary"
          onClick={() => dialogRef.current.close('cancel')}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => dialogRef.current.close('confirm')}
        >
          {confirmLabel}
        </button>
      </div>
    </dialog>
  )
}
