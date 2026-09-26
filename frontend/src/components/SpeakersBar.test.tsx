import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SpeakersBar } from './SpeakersBar'

const VOICES = [
  { voice_id: 'nPczCjzI2devNBz1zQrb', name: 'Brian', description: '', gender: 'male', accent: null, age: null },
]
const SPEAKERS = [
  { label: 'A', name: 'Speaker A', voice_id: null },
  { label: 'B', name: 'Shopkeeper', voice_id: 'nPczCjzI2devNBz1zQrb' },
]
const noop = () => {}

describe('SpeakersBar', () => {
  it('offers detection when speakers are unknown', async () => {
    const onDetect = vi.fn()
    render(<SpeakersBar speakers={[]} voices={VOICES} hasSpeech detecting={false}
      onDetect={onDetect} onRename={noop} onVoice={noop} />)
    await userEvent.click(screen.getByRole('button', { name: /detect speakers/i }))
    expect(onDetect).toHaveBeenCalled()
  })

  it('shows nothing for a video without speech', () => {
    const { container } = render(<SpeakersBar speakers={[]} voices={VOICES} hasSpeech={false}
      detecting={false} onDetect={noop} onRename={noop} onVoice={noop} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renames a speaker when the name is committed', async () => {
    const onRename = vi.fn()
    render(<SpeakersBar speakers={SPEAKERS} voices={VOICES} hasSpeech detecting={false}
      onDetect={noop} onRename={onRename} onVoice={noop} />)
    const name = screen.getByRole('textbox', { name: 'Name for speaker A' })
    await userEvent.clear(name)
    await userEvent.type(name, 'Customer{Enter}')
    expect(onRename).toHaveBeenCalledWith('A', 'Customer')
  })

  it("sets a speaker's voice, or returns them to the chat's voice", async () => {
    const onVoice = vi.fn()
    render(<SpeakersBar speakers={SPEAKERS} voices={VOICES} hasSpeech detecting={false}
      onDetect={noop} onRename={noop} onVoice={onVoice} />)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Voice for Speaker A' }), 'nPczCjzI2devNBz1zQrb')
    expect(onVoice).toHaveBeenLastCalledWith('A', 'nPczCjzI2devNBz1zQrb')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Voice for Shopkeeper' }), "Chat's voice")
    expect(onVoice).toHaveBeenLastCalledWith('B', null)
  })
})
