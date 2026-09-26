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
    expect(screen.getByText(/1 edit ·/)).toBeInTheDocument()
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

  it('shows nothing when there are no projects', () => {
    const { container } = render(<ProjectList projects={[]} onOpen={() => {}} onDelete={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
