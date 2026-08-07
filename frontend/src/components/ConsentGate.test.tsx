import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConsentGate } from './ConsentGate'

describe('ConsentGate', () => {
  it('shows the consent copy and gates Continue on the checkbox', async () => {
    const onConfirm = vi.fn()
    render(<ConsentGate onConfirm={onConfirm} />)
    expect(
      screen.getByText(/right to edit and clone the speaker/i),
    ).toBeInTheDocument()

    const button = screen.getByRole('button', { name: /continue/i })
    expect(button).toBeDisabled()

    await userEvent.click(screen.getByRole('checkbox'))
    expect(button).toBeEnabled()

    await userEvent.click(button)
    expect(onConfirm).toHaveBeenCalledOnce()
  })
})
