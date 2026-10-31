import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import NotesList from '../NotesList'
import { listed } from './fixtures'

describe('NotesList', () => {
  it('shows only a loading message while loading', () => {
    render(<NotesList notes={[{ id: 1, content: 'Hidden' }]} loading={true} />)

    expect(screen.getByText('Loading notes...')).toBeInTheDocument()
    // The page's status line announces it, so this is not a second live region
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByText('Hidden')).not.toBeInTheDocument()
    expect(screen.queryByText(/no notes yet/i)).not.toBeInTheDocument()
  })

  it('invites a first note when there are none', () => {
    render(<NotesList notes={[]} loading={false} loaded={true} />)

    expect(screen.getByText(/no notes yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('claims nothing about the notes before they have loaded', () => {
    render(<NotesList notes={[]} loading={false} loaded={false} />)

    expect(screen.queryByText(/no notes yet/i)).not.toBeInTheDocument()
  })

  // The id counts across all users, so it would mean nothing to this one
  it('lists each note by its text alone, never its id, in the order given', () => {
    render(<NotesList notes={[{ id: 3, content: 'Third' }, { id: 1, content: 'First' }]} loading={false} />)

    expect(listed()).toEqual(['Third', 'First'])
  })

  it.each([
    [0, 'Edit', 'Third'],
    [1, 'Delete', 'Third'],
    [2, 'Edit', 'First'],
    [3, 'Delete', 'First'],
  ])('offers Edit and Delete per note, named by their labels and described by its text (button %i)', (index, name, text) => {
    render(<NotesList notes={[{ id: 3, content: 'Third' }, { id: 1, content: 'First' }]} loading={false} />)

    const button = screen.getAllByRole('button')[index]
    expect(button).toHaveAccessibleName(name)
    expect(button).toHaveAccessibleDescription(text)
  })

  it('shows markup as text, never as HTML', () => {
    // The backend stores notes verbatim; React's escaping is the only guard
    const content = '<img src=x onerror="window.pwned=1"><b>bold</b>'
    const { container } = render(<NotesList notes={[{ id: 1, content }]} loading={false} />)

    expect(screen.getByText(content)).toBeInTheDocument()
    expect(container.querySelector('img, b')).toBeNull()
  })

  it('shows quotes and other Unicode as typed', () => {
    const content = 'He said "hi" & it\'s — ünïcode'
    render(<NotesList notes={[{ id: 1, content }]} loading={false} />)

    expect(screen.getByText(content)).toBeInTheDocument()
  })
})
