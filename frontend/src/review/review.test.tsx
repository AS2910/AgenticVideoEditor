import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SharePage } from '../pages/SharePage'
import { SendForReview } from './SendForReview'
import { ReviewComments } from './Comments'
import { commentGoal } from './useReviewComments'
import { feedItems } from '../pages/feedWords'
import type { ProjectEvent, ReviewComment } from '../types'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response

const REVIEW = (extra: Record<string, unknown> = {}) => ({
  scope: 'video', role: 'reviewer', name: 'Priya', expires_at: '2026-11-20T10:00:00.000Z', title: 'bhaji-cam.mp4',
  files: [{ file_id: 'p1-bbb', name: 'bhaji-cam-voltage.mp4', kind: 'video', size: 1000, duration: 30, video_id: 'p1' }],
  review: {
    reviewer: 'Priya', allow_download: false,
    videos: [{
      video_id: 'p1', title: 'bhaji-cam.mp4', duration: 30, current_version: 5, answer: null, comments: [],
      versions: [
        { version: 5, file_id: 'p1-bbb', duration: 30, created_at: '2026-10-21T10:00:00.000Z', against: 'v3', changes: ['0:04 now says "Get 30% off"'] },
        { version: 3, file_id: 'p1-aaa', duration: 30, created_at: '2026-10-20T10:00:00.000Z', against: 'as shot', changes: [] },
      ],
    }],
  },
  ...extra,
})

describe('C2: the review page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('plays the latest version with a watermark and no download, shows what changed, and picks another version', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok(REVIEW())))
    render(<SharePage token="sh1.sig" />)
    expect(await screen.findByRole('heading', { name: 'bhaji-cam.mp4' })).toBeInTheDocument()
    expect(screen.getByTestId('share-meta')).toHaveTextContent('For Priya · 1 video to review')
    const player = screen.getByLabelText('bhaji-cam.mp4, version 5')
    expect(player).toHaveAttribute('src', '/api/share/sh1.sig/files/p1-bbb')
    expect(player).toHaveAttribute('controlsList', 'nodownload')
    expect(screen.getByTestId('watermark')).toHaveTextContent('Review copy · Priya')
    expect(screen.queryByRole('link', { name: /Download/ })).toBeNull()
    expect(screen.getByTestId('what-changed')).toHaveTextContent('What changed in v5 · against v3')
    expect(screen.getByTestId('what-changed')).toHaveTextContent('0:04 now says "Get 30% off"')
    await userEvent.click(within(screen.getByTestId('version-picker')).getByRole('button', { name: 'v3' }))
    expect(screen.getByLabelText('bhaji-cam.mp4, version 3')).toHaveAttribute('src', '/api/share/sh1.sig/files/p1-aaa')
    expect(screen.getByTestId('what-changed')).toHaveTextContent('This is the video as shot.')
  })

  it('offers Download only when the link allows it', async () => {
    const body = REVIEW()
    body.review.allow_download = true
    vi.stubGlobal('fetch', vi.fn(async () => ok(body)))
    render(<SharePage token="sh1.sig" />)
    expect(await screen.findByRole('link', { name: 'Download v5' })).toHaveAttribute('href', '/api/share/sh1.sig/files/p1-bbb?download=true')
    expect(screen.queryByTestId('watermark')).toBeNull()
  })

  it('pins a comment to the playing time and approves with a note', async () => {
    const posts: { url: string; body: Record<string, unknown> }[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        posts.push({ url, body })
        if (url.endsWith('/comments')) return ok({ comment_id: 1, author: 'Priya', at_s: body.at_s, version: body.version, text: body.text, status: 'open', created_at: '', replies: [] }, 201)
        return ok({ video_id: 'p1', answer: { answer: 'approved', by: 'Priya', version: 5, note: 'Lovely', at: '2026-10-21T11:00:00.000Z' } })
      }
      return ok(REVIEW())
    }))
    render(<SharePage token="sh1.sig" />)
    const player = await screen.findByLabelText('bhaji-cam.mp4, version 5') as HTMLVideoElement
    player.currentTime = 12.4
    player.dispatchEvent(new Event('timeupdate'))
    await waitFor(() => expect(screen.getByTestId('comment-form')).toHaveTextContent('Comment at 0:12 in v5'))
    await userEvent.type(screen.getByLabelText(/Comment at/), 'Logo bigger here')
    await userEvent.click(screen.getByRole('button', { name: 'Add comment at 0:12' }))
    expect(await screen.findByTestId('review-comment')).toHaveTextContent('Logo bigger here')
    expect(posts[0]).toEqual({ url: '/api/share/sh1.sig/comments', body: { video_id: 'p1', at_s: 12.4, text: 'Logo bigger here', version: 5, name: 'Priya' } })
    const answer = screen.getByTestId('review-answer')
    const buttons = within(answer).getAllByRole('button')
    expect(buttons.map((b) => b.textContent)).toEqual(['Ask for changes', 'Approve v5'])   // approve last
    await userEvent.type(within(answer).getByLabelText(/Note/), 'Lovely')
    await userEvent.click(within(answer).getByRole('button', { name: 'Approve v5' }))
    expect(await screen.findByTestId('answer-said')).toHaveTextContent('Priya approved v5')
    expect(posts[1]).toEqual({ url: '/api/share/sh1.sig/approve', body: { video_id: 'p1', version: 5, note: 'Lovely', name: 'Priya' } })
  })

  it('says when nothing is rendered yet', async () => {
    const body = REVIEW()
    body.review.videos[0].versions = []
    body.review.videos[0].current_version = null as unknown as number
    vi.stubGlobal('fetch', vi.fn(async () => ok(body)))
    render(<SharePage token="sh1.sig" />)
    expect(await screen.findByTestId('review-empty')).toHaveTextContent('Nothing to watch yet.')
  })
})

describe('C2: Send for review', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('makes a link for the picked videos with name, email, expiry and download off, then lists it', async () => {
    const posts: { url: string; body: unknown }[] = []
    let shares: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) })
        const link = { share_id: 'sh9', scope: 'project', target: 'f1', role: 'reviewer', name: 'Priya', created_at: '', expires_at: '2026-11-20T10:00:00.000Z', revoked_at: null, state: 'live', url: 'http://x/#s/sh9.sig', data: { allow_download: false, email: 'p@c.io' } }
        shares = [link]
        return ok(link, 201)
      }
      return ok({ shares })
    }))
    const onSent = vi.fn()
    render(<SendForReview target={{ kind: 'project', projectId: 'f1', title: 'Diwali', videos: [{ video_id: 'p1', filename: 'a.mp4', stage_label: 'Draft' }, { video_id: 'p2', filename: 'b.mp4' }] }} onClose={() => {}} onSent={onSent} />)
    expect(await screen.findByText('No review links yet.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: /b\.mp4/ }))
    await userEvent.type(screen.getByLabelText(/Reviewer's name/), 'Priya')
    await userEvent.type(screen.getByLabelText(/Their email/), 'nope')
    expect(screen.getByText('That email address does not look right.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Make the link for 1 video' })).toBeDisabled()
    await userEvent.clear(screen.getByLabelText(/Their email/))
    await userEvent.type(screen.getByLabelText(/Their email/), 'p@c.io')
    expect(screen.getByRole('checkbox', { name: /Allow download/ })).not.toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: 'Make the link for 1 video' }))
    expect(await screen.findByRole('textbox', { name: 'Review link' })).toHaveValue('http://x/#s/sh9.sig')
    expect(posts[0]).toEqual({ url: '/api/projects/f1/shares', body: { scope: 'project', role: 'reviewer', name: 'Priya', email: 'p@c.io', days: 30, allow_download: false, videos: ['p1'] } })
    expect(onSent).toHaveBeenCalled()
    await waitFor(() => expect(screen.getAllByTestId('review-link')).toHaveLength(1))
    expect(screen.getByTestId('review-link')).toHaveTextContent('Watch only')
  })
})

const comment = (extra: Partial<ReviewComment> = {}): ReviewComment => ({
  comment_id: 1, video_id: 'p1', share_id: 'sh1', author_kind: 'reviewer', author_name: 'Priya', at_s: 12.4, version: 5,
  text: 'Logo bigger', status: 'open', replies: [], created_at: '2026-10-21T10:00:00.000Z', resolved_at: null, resolved_by: null, link_name: 'Priya', ...extra })

describe('C2: comments in the editor', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('seeks, replies, resolves and hands a comment to Voltage', async () => {
    const onSeek = vi.fn(), onAsk = vi.fn(), onChanged = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? '{}'))
      if (url.endsWith('/replies')) return ok(comment({ replies: [{ author_kind: 'user', author_name: 'local', text: body.text, at: '' }] }))
      return ok(comment({ status: 'resolved' }))
    }))
    render(<ReviewComments videoId="p1" comments={[comment(), comment({ comment_id: 2, status: 'resolved', text: 'Old one' })]} error={null} busy={false}
      onReload={() => {}} onSeek={onSeek} onAsk={onAsk} onChanged={onChanged} />)
    expect(screen.getByText('1 open · 1 resolved')).toBeInTheDocument()
    expect(screen.queryByText('Old one')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Go to 0:12' }))
    expect(onSeek).toHaveBeenCalledWith(12.4)
    await userEvent.click(screen.getByRole('button', { name: 'Do what the client asked' }))
    expect(onAsk).toHaveBeenCalledWith('Priya asked at 0:12 in v5: "Logo bigger". Do what they asked.')
    await userEvent.click(screen.getByRole('button', { name: 'Reply' }))
    await userEvent.type(screen.getByLabelText('Reply to Priya'), 'On it')
    await userEvent.click(screen.getByRole('button', { name: 'Send reply' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ replies: [expect.objectContaining({ text: 'On it' })] })))
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }))
    await waitFor(() => expect(onChanged).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'resolved' })))
    await userEvent.click(screen.getByRole('button', { name: 'Show 1 resolved' }))
    expect(screen.getByText('Old one')).toBeInTheDocument()
    expect(commentGoal(comment({ version: null, at_s: 75 }))).toBe('Priya asked at 1:15: "Logo bigger". Do what they asked.')
  })

  it('shows nothing with no comments, and a retry on a read error', async () => {
    const { container, rerender } = render(<ReviewComments videoId="p1" comments={[]} error={null} busy={false} onReload={() => {}} onSeek={() => {}} onAsk={() => {}} onChanged={() => {}} />)
    expect(container).toBeEmptyDOMElement()
    const onReload = vi.fn()
    rerender(<ReviewComments videoId="p1" comments={null} error="Could not read the comments." busy={false} onReload={onReload} onSeek={() => {}} onAsk={() => {}} onChanged={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onReload).toHaveBeenCalled()
  })

  it('says review events in the feed, folding a bare answer into its stage move', () => {
    const ev = (id: number, verb: string, payload: Record<string, unknown> = {}): ProjectEvent => ({ id, project_id: 'f1', video_id: 'p1', actor_kind: 'reviewer', actor_name: 'Priya', verb, target: 'sh1', payload, at: '' })
    const items = feedItems([ev(4, 'review.approved'), ev(3, 'review.changes_asked', { note: 'Shorter' }), ev(2, 'review.commented', { at_s: 12.4 })], () => 'a.mp4')
    expect(items.map((i) => i.text)).toEqual(['Priya asked for changes to a: "Shorter"', 'Priya commented on a at 0:12'])
  })
})
