import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import FormField from '../FormField'

const input = () => screen.getByLabelText('Password')

describe('FormField', () => {
  it('labels the input and passes its attributes through', () => {
    render(<FormField id="password" label="Password" type="password" autoComplete="new-password" />)

    expect(input()).toHaveAttribute('type', 'password')
    expect(input()).toHaveAttribute('name', 'password')
    expect(input()).toHaveAttribute('autocomplete', 'new-password')
    expect(input()).toHaveAttribute('aria-invalid', 'false')
    expect(input()).not.toHaveAttribute('aria-describedby')
  })

  it('reads the hint with the input', () => {
    render(<FormField id="password" label="Password" hint="At least 8 characters." />)

    expect(input()).toHaveAccessibleDescription('At least 8 characters.')
  })

  it('marks the input invalid and reads the message before the hint', () => {
    render(<FormField id="password" label="Password" hint="At least 8 characters." error="Too short" />)

    expect(input()).toHaveAttribute('aria-invalid', 'true')
    expect(input()).toHaveAccessibleDescription('Too short At least 8 characters.')
  })

  it('takes a name apart from its id, and shows its children', () => {
    render(
      <FormField id="edit-7" name="content" label="Password">
        <button type="submit">Save</button>
      </FormField>
    )

    expect(input()).toHaveAttribute('id', 'edit-7')
    expect(input()).toHaveAttribute('name', 'content')
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('puts a checkbox before its label, with its hint and message', () => {
    render(<FormField id="accept" label="I agree" type="checkbox" hint="Opens a new tab." error="Required" />)

    const checkbox = screen.getByRole('checkbox', { name: 'I agree' })
    expect(checkbox.compareDocumentPosition(screen.getByText('I agree')))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(checkbox).toHaveAttribute('aria-invalid', 'true')
    expect(checkbox).toHaveAccessibleDescription('Required Opens a new tab.')
  })
})
