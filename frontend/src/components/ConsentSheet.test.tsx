import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConsentSheet } from './ConsentSheet'

describe('ConsentSheet', () => {
  it('asks in a sentence, naming the speaker, and answers either way', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(<ConsentSheet who="the Shopkeeper" onConfirm={onConfirm} onCancel={onCancel} />)
    expect(screen.getByRole('dialog')).toHaveTextContent("I'll be creating speech in the Shopkeeper's voice")
    expect(screen.getByRole('dialog')).toHaveTextContent('You have their permission?')
    await userEvent.click(screen.getByRole('button', { name: 'Not yet' }))
    expect(onCancel).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Yes, I have it' }))
    expect(onConfirm).toHaveBeenCalled()
  })

  it('falls back to "this person" when the speaker is unknown', () => {
    render(<ConsentSheet onConfirm={() => {}} onCancel={() => {}} />)
    expect(screen.getByRole('dialog')).toHaveTextContent("in this person's voice")
  })
})
