import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WhatVoltageMayDo } from './WhatVoltageMayDo'

const VALUE = { autonomy: 'ask' as const, turn_usd: 0.5, effort: 'high' as const, ceiling_usd: 2 }

describe('WhatVoltageMayDo (20d)', () => {
  it('shows the three choices with labels and help, and saves each on change', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<WhatVoltageMayDo open value={VALUE} onChange={onChange} onClose={() => {}} />)
    const sheet = screen.getByRole('dialog', { name: 'What Voltage may do' })
    expect(within(sheet).getByRole('button', { name: 'Check with me' })).toHaveAttribute('aria-pressed', 'true')
    expect(sheet).toHaveTextContent('A change to the video, or a paid step over your limit, waits for your yes.')
    await user.click(within(sheet).getByRole('button', { name: 'Just do it' }))
    expect(onChange).toHaveBeenLastCalledWith({ autonomy: 'draft' })

    const cap = within(sheet).getByLabelText('One turn may spend')
    expect(cap).toHaveValue(0.5)
    expect(sheet).toHaveTextContent('of a $2.00 ceiling for the project')
    await user.clear(cap)
    await user.type(cap, '9{Enter}')
    expect(onChange).toHaveBeenLastCalledWith({ turn_usd: 2 })     // bounded by the ceiling
    expect(cap).toHaveValue(2)

    await user.click(within(sheet).getByRole('button', { name: 'Thorough' }))
    expect(onChange).toHaveBeenLastCalledWith({ effort: 'xhigh' })
    expect(within(sheet).getByRole('button', { name: 'Careful' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('Run 5 item 2: under Check with me it names the spending limit and points to Settings', () => {
    render(<WhatVoltageMayDo open value={{ ...VALUE, ask_over_usd: 0.25 }} onChange={() => {}} onClose={() => {}} />)
    const help = screen.getByTestId('may-do-help')
    expect(help).toHaveTextContent('Paid steps up to $0.25 a turn go ahead; more than that, and changes to the video, wait for your yes.')
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '#settings')
  })

  it('leaves an unchanged choice alone and closes with Escape', async () => {
    const onChange = vi.fn()
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(<WhatVoltageMayDo open value={VALUE} onChange={onChange} onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: 'Check with me' }))
    expect(onChange).not.toHaveBeenCalled()
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})
