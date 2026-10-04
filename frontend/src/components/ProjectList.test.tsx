import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectList } from './ProjectList'

const PROJECTS = [
  { project_id: 'p2', filename: 'bhaji.mp4', duration: 48.9, created_at: '2026-09-26T08:00:00Z', edits: 1 },
  { project_id: 'p1', filename: 'crow.mp4', duration: 8, created_at: '2026-09-26T07:00:00Z', edits: 0 },
]

describe('ProjectList', () => {
  it('lists projects and opens one', async () => {
    const onOpen = vi.fn()
    render(<ProjectList projects={PROJECTS} onOpen={onOpen} onDelete={() => {}} />)
    expect(screen.getByText(/48\.9 s, 1 edit$/)).toBeInTheDocument()
    await userEvent.click(screen.getByText('crow.mp4'))
    expect(onOpen).toHaveBeenCalledWith('p1')
  })

  it('asks once more before deleting', async () => {
    const onDelete = vi.fn()
    render(<ProjectList projects={PROJECTS} onOpen={() => {}} onDelete={onDelete} />)
    await userEvent.click(screen.getByRole('button', { name: 'Delete crow.mp4' }))
    expect(onDelete).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /delete for good/i }))
    expect(onDelete).toHaveBeenCalledWith('p1')
  })

  it('can back out of a delete', async () => {
    const onDelete = vi.fn()
    render(<ProjectList projects={PROJECTS} onOpen={() => {}} onDelete={onDelete} />)
    await userEvent.click(screen.getByRole('button', { name: 'Delete crow.mp4' }))
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }))
    expect(screen.queryByRole('button', { name: /delete for good/i })).not.toBeInTheDocument()
    expect(onDelete).not.toHaveBeenCalled()
  })

  it('shows a frame, where each stands and its last change (UX-3)', () => {
    const rich = [
      { ...PROJECTS[0], media: { kind: 'video' as const, sha256: 's'.repeat(64), duration: 48.9, container: 'mp4' }, state: 'shipped' as const, last_change: 'Rendered the edited video' },
      { ...PROJECTS[1], project_id: 'p3', state: 'draft' as const, last_change: 'Planned 2 changes', variant_of: 'p2' },
    ]
    const { container } = render(<ProjectList projects={rich} onOpen={() => {}} onDelete={() => {}} />)
    expect(container.querySelector('video')).toHaveAttribute('src', `/api/projects/p2/artifacts/${'s'.repeat(64)}#t=0.5`)
    expect(screen.getByText('Shipped')).toBeInTheDocument()
    expect(screen.getByText(/Rendered the edited video/)).toBeInTheDocument()
    expect(screen.getByText('Draft')).toBeInTheDocument()
    expect(screen.getByText('variant of bhaji.mp4')).toBeInTheDocument()
  })

  it('shows nothing when there are no projects', () => {
    const { container } = render(<ProjectList projects={[]} onOpen={() => {}} onDelete={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
