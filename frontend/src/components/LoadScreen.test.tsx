import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoadScreen } from './LoadScreen'

describe('LoadScreen', () => {
  it('calls onLoad when the button is clicked', async () => {
    const onLoad = vi.fn()
    render(<LoadScreen onLoad={onLoad} loading={false} />)
    await userEvent.click(screen.getByRole('button', { name: /load sample ad/i }))
    expect(onLoad).toHaveBeenCalledOnce()
  })

  it('disables and relabels the button while loading', () => {
    render(<LoadScreen onLoad={() => {}} loading={true} />)
    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
    expect(button).toHaveTextContent(/loading/i)
  })
})
