import { describe, it, expect, vi } from 'vitest'
import { StrictMode, useState } from 'react'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FormDialog from '../FormDialog'
import FormField from '@/components/forms/FormField'

// A button that opens the dialog, as callers use it: rendered only while
// asking, and closed only by onCancel, as a submit leaves it to the page
function Asker({ busy = false, onSubmit, onCancel }) {
  const [asking, setAsking] = useState(false)
  const [code, setCode] = useState('')
  return (
    <>
      <button type="button" onClick={() => setAsking(true)}>Remove</button>
      {asking && (
        <FormDialog
          title="Remove it?"
          description="There is no undo."
          submitLabel="Remove for good"
          busy={busy}
          onSubmit={onSubmit}
          onCancel={() => { setAsking(false); onCancel() }}
        >
          <FormField id="code" label="Code" value={code} onChange={e => setCode(e.target.value)} />
        </FormDialog>
      )}
    </>
  )
}

async function open({ strict = false } = {}) {
  const onSubmit = vi.fn()
  const onCancel = vi.fn()
  const user = userEvent.setup()
  const asker = busy => {
    const element = <Asker busy={busy} onSubmit={onSubmit} onCancel={onCancel} />
    return strict ? <StrictMode>{element}</StrictMode> : element
  }
  const { rerender } = render(asker(false))
  await user.click(screen.getByRole('button', { name: 'Remove' }))
  return { user, onSubmit, onCancel, setBusy: busy => rerender(asker(busy)) }
}

const dialog = () => screen.getByRole('dialog', { name: 'Remove it?' })
const opener = () => screen.getByRole('button', { name: 'Remove' })

describe('FormDialog', () => {
  it('opens named by its title, described by its description, on its first field', async () => {
    await open()

    expect(dialog()).toHaveAttribute('open')
    expect(dialog()).toHaveAccessibleDescription('There is no undo.')
    expect(screen.getByLabelText('Code')).toHaveFocus()
  })

  it('hands the submit to the page and stays open', async () => {
    const { user, onSubmit, onCancel } = await open()
    await user.type(screen.getByLabelText('Code'), '1234')

    await user.click(screen.getByRole('button', { name: 'Remove for good' }))

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit.mock.calls[0][0].defaultPrevented).toBe(true)
    expect(onCancel).not.toHaveBeenCalled()
    expect(dialog()).toHaveAttribute('open')
  })

  it.each([
    ['Cancel', user => user.click(screen.getByRole('button', { name: 'Cancel' }))],
    ['Escape', user => user.keyboard('{Escape}')],
  ])('cancels on %s, then returns focus to the opener', async (_, cancel) => {
    const { user, onSubmit, onCancel } = await open()

    await cancel(user)

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener()).toHaveFocus()
  })

  it('ignores Cancel, Escape and a repeat submit while busy', async () => {
    const { user, onSubmit, onCancel, setBusy } = await open()
    setBusy(true)

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('button', { name: 'Remove for good' }))

    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('button', { name: 'Remove for good' })).toHaveAttribute('aria-disabled', 'true')
    expect(onCancel).not.toHaveBeenCalled()
    expect(onSubmit).not.toHaveBeenCalled()
    expect(dialog()).toHaveAttribute('open')
  })

  // A browser closes it on a repeated Escape with no user activation between
  it('closed by the browser anyway, it cancels', async () => {
    const { onCancel } = await open()

    act(() => dialog().close())

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('closed by the browser while busy, it opens again', async () => {
    const { onCancel, setBusy } = await open()
    setBusy(true)

    act(() => dialog().close())

    expect(onCancel).not.toHaveBeenCalled()
    expect(dialog()).toHaveAttribute('open')
  })

  it('opens once under Strict Mode, which runs its effect twice', async () => {
    const { user, onCancel } = await open({ strict: true })
    expect(screen.getByLabelText('Code')).toHaveFocus()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(opener()).toHaveFocus()
  })
})
