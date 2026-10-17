import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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

it('groups the voices by accent once there is more than one (15e)', () => {
  const voices = [
    { voice_id: 'nPczCjzI2devNBz1zQrb', name: 'Brian', description: '', gender: 'male', accent: 'american', age: null },
    { voice_id: 'kL06KYMvPY56NluIQ72m', name: 'Varsha', description: 'Warm and Clear', gender: 'female', accent: 'indian', age: 'middle_aged' },
    { voice_id: 'vYENaCJHl4vFKNDYPr8y', name: 'Riya Rao', description: '', gender: 'female', accent: 'indian', age: null },
  ]
  render(<VoicePicker voices={voices} value="kL06KYMvPY56NluIQ72m" onChange={() => {}} />)
  const groups = screen.getAllByRole('group')
  expect(groups.map((g) => g.getAttribute('label'))).toEqual(['American', 'Indian'])
  expect(within(groups[1]).getAllByRole('option').map((o) => o.textContent)).toEqual(['Varsha (female, indian)', 'Riya Rao (female, indian)'])
})
