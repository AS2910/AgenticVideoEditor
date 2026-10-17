import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Markdown } from './Markdown'
import { parse } from '@/lib/markdown'

describe('Markdown', () => {
  it('leaves a plain sentence as one text node, findable whole', () => {
    const { container } = render(<Markdown text="This editor only changes spoken dialogue." />)
    expect(screen.getByText('This editor only changes spoken dialogue.')).toBeInTheDocument()
    expect(container.querySelectorAll('p, ul, ol, strong')).toHaveLength(0)
  })

  it('draws bold, italic, code and a link', () => {
    render(<Markdown text='Say **Bhaji Cam**, not *Bajicam*; the `brand` field. See [docs](https://example.com/x).' />)
    expect(screen.getByText('Bhaji Cam').tagName).toBe('STRONG')
    expect(screen.getByText('Bajicam').tagName).toBe('EM')
    expect(screen.getByText('brand').tagName).toBe('CODE')
    const a = screen.getByRole('link', { name: 'docs' })
    expect(a).toHaveAttribute('href', 'https://example.com/x')
    expect(a).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('never links to anything but http(s)', () => {
    render(<Markdown text="[x](javascript:alert(1)) and [y](https://ok.example)" />)
    expect(screen.queryByRole('link', { name: 'x' })).toBeNull()
    expect(screen.getByRole('link', { name: 'y' })).toBeInTheDocument()
  })

  it('never passes HTML through', () => {
    const { container } = render(<Markdown text="<b>bold</b> <img src=x onerror=alert(1)>" />)
    expect(container.querySelector('b, img')).toBeNull()
    expect(container.textContent).toContain('<b>bold</b>')
  })

  it('makes paragraphs, bullet and numbered lists, and a heading as a bold line', () => {
    const text = '## What I changed\n\nTwo things:\n- the brand name\n- the offer\n\nThen:\n1. voice it\n2. show you'
    const { container } = render(<Markdown text={text} />)
    expect(parse(text).map((b) => b.kind)).toEqual(['h', 'p', 'ul', 'p', 'ol'])
    expect(container.querySelectorAll('ul > li')).toHaveLength(2)
    expect(container.querySelectorAll('ol > li')).toHaveLength(2)
    expect(container.querySelector('h1, h2, h3')).toBeNull()
    expect(screen.getByText('What I changed').className).toContain('font-semibold')
  })

  it('keeps a single newline as a line break', () => {
    const { container } = render(<Markdown text={"line one\nline two"} />)
    expect(container.querySelectorAll('br')).toHaveLength(1)
  })

  it('does not take an asterisk in prose for emphasis', () => {
    const { container } = render(<Markdown text="2 * 3 = 6 and snake_case_name stays" />)
    expect(container.querySelector('em')).toBeNull()
    expect(container.textContent).toBe('2 * 3 = 6 and snake_case_name stays')
  })
})
