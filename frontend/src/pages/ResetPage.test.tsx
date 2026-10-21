import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ResetPage } from './ResetPage'
import { parseRoute, hrefFor } from '../lib/route'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response

describe('ResetPage (launch item 5)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('routes #reset/<token> and #login?error=', () => {
    expect(parseRoute('#reset/abc_DEF-1')).toEqual({ page: 'reset', token: 'abc_DEF-1' })
    expect(hrefFor({ page: 'reset', token: 'x' })).toBe('#reset/x')
    expect(parseRoute('#login?error=That%20link%20has%20expired.')).toEqual({ page: 'login', error: 'That link has expired.' })
  })

  it('needs the password twice, then sets it and signs in', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      return ok({ signed_in: true, email: 'ann@example.com' })
    }))
    const onDone = vi.fn()
    render(<ResetPage token="tok" onDone={onDone} />)
    await userEvent.type(screen.getByLabelText('New password'), 'a brand new password')
    await userEvent.type(screen.getByLabelText('The same again'), 'a brand new passwor')
    expect(screen.getByText('The two do not match yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save and sign in' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText('The same again'), 'd')
    await userEvent.click(screen.getByRole('button', { name: 'Save and sign in' }))
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(calls).toContain('POST /api/auth/password/reset {"token":"tok","password":"a brand new password"}')
  })
})
