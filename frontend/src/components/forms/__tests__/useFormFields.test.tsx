import { describe, it, expect } from 'vitest'
import type { ChangeEvent } from 'react'
import { renderHook, act } from '@testing-library/react'
import { useFormFields } from '../useFormFields'

// A form holding one field, as FormField renders it
function formWith(name: string, type = 'text') {
  const form = document.createElement('form')
  const input = document.createElement('input')
  input.name = name
  input.type = type
  form.append(input)
  return { form, input }
}

// The change event React hands a field's onChange
const changeOf = (input: HTMLInputElement) => ({ target: input }) as ChangeEvent<HTMLInputElement>

describe('useFormFields', () => {
  it.each([
    ['the starting values', undefined, { content: 'Start' }],
    ['the values given', { content: 'Next' }, { content: 'Next' }],
  ])('reset goes back to %s, with no messages', (_, nextValues, expected) => {
    const { result } = renderHook(() => useFormFields({ content: 'Start' }))
    const { form, input } = formWith('content')
    input.value = 'Typed'
    act(() => result.current.handleChange(changeOf(input)))
    act(() => { result.current.validate(form, { content: 'Too short' }) })
    expect(result.current.errors).toEqual({ content: 'Too short' })

    act(() => result.current.reset(nextValues))

    expect(result.current.values).toEqual(expected)
    expect(result.current.errors).toEqual({})
  })

  it('takes whether a checkbox is ticked as its value, and clears its message', () => {
    const { result } = renderHook(() => useFormFields({ accept: false }))
    const { form, input } = formWith('accept', 'checkbox')
    act(() => { result.current.validate(form, { accept: 'Required' }) })

    input.checked = true
    act(() => result.current.handleChange(changeOf(input)))

    expect(result.current.values).toEqual({ accept: true })
    expect(result.current.errors).toEqual({ accept: undefined })
  })

  it('focuses the first invalid field', () => {
    const { result } = renderHook(() => useFormFields({ content: '' }))
    const { form, input } = formWith('content')
    document.body.append(form)

    act(() => { result.current.validate(form, { content: 'Required' }) })

    expect(input).toHaveFocus()
    form.remove()
  })
})
