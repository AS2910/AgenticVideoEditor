import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoadScreen } from './LoadScreen'

const noop = () => {}

function setup(props: Partial<Parameters<typeof LoadScreen>[0]> = {}) {
  const onLoad = vi.fn()
  const onLoadSample = vi.fn()
  render(
    <LoadScreen onLoad={onLoad} onLoadSample={onLoadSample} loading={false} {...props} />,
  )
  return { onLoad, onLoadSample }
}

describe('LoadScreen', () => {
  it('hands the chosen file to onLoad', async () => {
    const { onLoad } = setup()
    const file = new File(['video-bytes'], 'my-ad.mp4', { type: 'video/mp4' })

    await userEvent.upload(screen.getByLabelText(/choose a video/i), file)

    expect(onLoad).toHaveBeenCalledOnce()
    expect(onLoad.mock.calls[0][0]).toBe(file)
  })

  it('offers the bundled sample as a separate action', async () => {
    const { onLoad, onLoadSample } = setup()
    await userEvent.click(screen.getByRole('button', { name: /sample ad/i }))
    expect(onLoadSample).toHaveBeenCalledOnce()
    expect(onLoad).not.toHaveBeenCalled()
  })

  it('disables both actions and relabels while uploading', () => {
    setup({ onLoad: noop, loading: true })
    expect(screen.getByRole('button', { name: /uploading/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /sample ad/i })).toBeDisabled()
  })

  it('shows the rejection reason when one is given', () => {
    setup({ error: 'That file has no video track.' })
    expect(screen.getByText(/no video track/i)).toBeInTheDocument()
  })

  it('states the limits up front', () => {
    setup()
    expect(screen.getByText(/3 minutes/i)).toBeInTheDocument()
  })
})
