import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VoicePicker } from './VoicePicker'

const VOICES = [
  { voice_id: 'EXAVITQu4vr4xnSDxMaL', name: 'Sarah', description: 'Mature', gender: 'female', accent: 'american', age: 'young' },
  { voice_id: 'nPczCjzI2devNBz1zQrb', name: 'Brian', description: 'Deep, Resonant', gender: 'male', accent: 'american', age: 'middle_aged' },
]

describe('VoicePicker', () => {
  it('names each voice with its gender and accent, and reports a change', async () => {
    const onChange = vi.fn()
    render(<VoicePicker voices={VOICES} value="EXAVITQu4vr4xnSDxMaL" onChange={onChange} />)
    expect(screen.getByRole('option', { name: 'Brian (male, american)' })).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByRole('combobox'), 'nPczCjzI2devNBz1zQrb')
    expect(onChange).toHaveBeenCalledWith('nPczCjzI2devNBz1zQrb')
  })

  it('is hidden until voices load', () => {
    const { container } = render(<VoicePicker voices={[]} value="" onChange={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
