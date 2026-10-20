import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { useFlags, resetFlags } from './useFlags'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response

function Probe() {
  const flags = useFlags()
  if (flags.loading) return <p>loading</p>
  return <p>{flags.enabled('projects.batch') ? 'batch on' : 'batch off'} {flags.enabled('projects.review') ? 'review on' : 'review off'}</p>
}

describe('useFlags', () => {
  beforeEach(() => resetFlags())
  afterEach(() => vi.unstubAllGlobals())

  it('reads the flags that are on for you, once for every component', async () => {
    const f = vi.fn(async () => ok({ flags: ['projects.batch', 'golive.g2'] }))
    vi.stubGlobal('fetch', f)
    render(<><Probe /><Probe /></>)
    expect(screen.getAllByText('loading')).toHaveLength(2)
    await waitFor(() => expect(screen.getAllByText('batch on review off')).toHaveLength(2))
    expect(f).toHaveBeenCalledTimes(1)
    expect(f).toHaveBeenCalledWith('/api/me/flags')
  })

  it('keeps everything off when the read fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}), text: async () => 'no' }) as Response))
    render(<Probe />)
    await waitFor(() => expect(screen.getByText('batch off review off')).toBeTruthy())
  })
})
