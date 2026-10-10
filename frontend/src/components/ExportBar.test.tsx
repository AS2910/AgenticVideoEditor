import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExportBar } from './ExportBar'
import type { MediaArtifact, Segment } from '../types'

// Every span resolves to the artifact it is composited from: originals to the
// source, edits to their generated frames.
const SOURCE: MediaArtifact = { kind: 'video', sha256: 's'.repeat(64), duration: 3, container: 'mp4' }
const FRAMES: MediaArtifact = { kind: 'video', sha256: 'f'.repeat(64), duration: 0.9, container: 'mp4' }

const SEGMENTS: Segment[] = [
  { start: 0, end: 0.4, kind: 'original', ref: 'ad.mp4', artifact: SOURCE },
  { start: 0.4, end: 1.3, kind: 'edited', ref: FRAMES.sha256, artifact: FRAMES },
  { start: 1.3, end: 3, kind: 'original', ref: 'ad.mp4', artifact: SOURCE },
]

describe('ExportBar', () => {
  it('calls onExport when clicked', async () => {
    const onExport = vi.fn()
    render(<ExportBar segments={[]} onExport={onExport} />)
    await userEvent.click(screen.getByRole('button', { name: /export/i }))
    expect(onExport).toHaveBeenCalledOnce()
  })

  it('offers the rendered MP4 as a download once there is one', () => {
    render(
      <ExportBar segments={SEGMENTS} onExport={() => {}}
        download={{ url: '/api/projects/p1/artifacts/abc', filename: 'ad-edited.mp4' }} />,
    )
    const link = screen.getByRole('link', { name: /download mp4/i })
    expect(link).toHaveAttribute('href', '/api/projects/p1/artifacts/abc')
    expect(link).toHaveAttribute('download', 'ad-edited.mp4')
  })

  it('offers no download before an export has run', () => {
    render(<ExportBar segments={[]} onExport={() => {}} />)
    expect(screen.queryByRole('link', { name: /download/i })).not.toBeInTheDocument()
  })

  it('renders no strip before an export has run', () => {
    render(<ExportBar segments={[]} onExport={() => {}} />)
    expect(screen.queryAllByTestId('segment')).toHaveLength(0)
  })

  it('renders one strip block per segment', () => {
    render(<ExportBar segments={SEGMENTS} onExport={() => {}} />)
    expect(screen.getAllByTestId('segment')).toHaveLength(3)
    const edited = screen.getAllByTestId('segment').filter(
      (el) => el.getAttribute('data-kind') === 'edited',
    )
    expect(edited).toHaveLength(1)
  })

  it('sizes each block in proportion to its span', () => {
    render(<ExportBar segments={SEGMENTS} onExport={() => {}} />)
    const [first, second] = screen.getAllByTestId('segment')
    // 0.4 of 3.0 total ≈ 13.33%, 0.9 of 3.0 = 30%
    expect(first.style.width).toMatch(/^13\.33/)
    expect(second.style.width).toBe('30%')
  })
})

describe('ExportBar inserts', () => {
  it('says how many lines were added and for how long', () => {
    const artifact = { kind: 'audio' as const, sha256: 'a'.repeat(64), duration: 0.74, container: 'wav' }
    render(
      <ExportBar
        segments={[]}
        onExport={() => {}}
        inserts={[{ at: 5.9, duration: 0.74, artifact }]}
      />,
    )
    expect(screen.getByTestId('inserts')).toHaveTextContent('+1 added line; the picture makes room for 0.74 s.')
  })

  it('says how the picture made room, what was held, and what flexed (Phase 16)', () => {
    const artifact = { kind: 'audio' as const, sha256: 'a'.repeat(64), duration: 0.74, container: 'wav' }
    const pieces = [
      { start: 0, end: 2.0, out_start: 0, out_end: 2.2, kind: 'flex' as const, factor: 1.1 },
      { start: 2.0, end: 5.9, out_start: 2.2, out_end: 6.1, kind: 'copy' as const, factor: 1 },
      { start: 5.9, end: 6.4, out_start: 6.1, out_end: 6.9, kind: 'living' as const, factor: 1.6 },
      { start: 6.4, end: 6.4, out_start: 6.9, out_end: 7.14, kind: 'hold' as const, factor: null },
      { start: 6.4, end: 9.0, out_start: 7.14, out_end: 9.74, kind: 'copy' as const, factor: 1 },
    ]
    render(<ExportBar segments={[]} onExport={() => {}} inserts={[{ at: 5.9, duration: 0.74, artifact, held: 0.24 }]} pieces={pieces} />)
    // Room = the living piece's 0.8 s plus the held 0.24 s; the hold is said only because there is one.
    expect(screen.getByTestId('inserts')).toHaveTextContent('+1 added line; the picture makes room for 1.04 s, 0.24 s of it held. 1 line flexed the picture by up to 10%.')
  })

  it('says only what flexed when nothing was added', () => {
    render(<ExportBar segments={[]} onExport={() => {}} pieces={[{ start: 0, end: 1, out_start: 0, out_end: 0.92, kind: 'flex', factor: 0.92 }]} />)
    expect(screen.getByTestId('inserts')).toHaveTextContent('1 line flexed the picture by up to 8%.')
  })
})
