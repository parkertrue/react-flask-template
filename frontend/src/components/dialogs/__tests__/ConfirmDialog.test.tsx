import { describe, it, expect, vi } from 'vitest'
import { StrictMode, useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import ConfirmDialog from '../ConfirmDialog'

// A button that opens the dialog, as callers use it: rendered only while asking
function Asker({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  const [asking, setAsking] = useState(false)
  const done = (callback: () => void) => () => { setAsking(false); callback() }
  return (
    <>
      <button type="button" onClick={() => setAsking(true)}>Remove</button>
      {asking && (
        <ConfirmDialog
          title="Remove it?"
          confirmLabel="Remove for good"
          onConfirm={done(onConfirm)}
          onCancel={done(onCancel)}
        >
          <p>There is no undo.</p>
        </ConfirmDialog>
      )}
    </>
  )
}

async function open({ strict = false } = {}) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  const user = userEvent.setup()
  const asker = <Asker onConfirm={onConfirm} onCancel={onCancel} />
  render(strict ? <StrictMode>{asker}</StrictMode> : asker)
  await user.click(screen.getByRole('button', { name: 'Remove' }))
  return { user, onConfirm, onCancel }
}

describe('ConfirmDialog', () => {
  it('opens named by its title, described by its body, on Cancel', async () => {
    await open()

    const dialog = screen.getByRole('dialog', { name: 'Remove it?' })
    expect(dialog).toHaveAttribute('open')
    expect(dialog).toHaveAccessibleDescription('There is no undo.')
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('confirms with the confirm button, then returns focus to the opener', async () => {
    const { user, onConfirm, onCancel } = await open()

    await user.click(screen.getByRole('button', { name: 'Remove for good' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toHaveFocus()
  })

  it.each([
    ['Cancel', (user: UserEvent) => user.click(screen.getByRole('button', { name: 'Cancel' }))],
    ['Escape', (user: UserEvent) => user.keyboard('{Escape}')],
  ])('cancels on %s, then returns focus to the opener', async (_, cancel) => {
    const { user, onConfirm, onCancel } = await open()

    await cancel(user)

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toHaveFocus()
  })

  it('opens once under Strict Mode, which runs its effect twice', async () => {
    const { user, onConfirm, onCancel } = await open({ strict: true })
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()

    await user.click(screen.getByRole('button', { name: 'Remove for good' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Remove' })).toHaveFocus()
  })
})
