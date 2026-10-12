import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Markdown } from './Markdown'

describe('Markdown', () => {
  it('renders headings, emphasis, lists, links, inline code, and citations', () => {
    render(<Markdown content={'## A heading\n\nA **bold** point with `code` and [a source](https://example.test/source). [S2]\n\n- First\n- Second'} />)

    expect(screen.getByRole('heading', { name: 'A heading' })).toBeTruthy()
    expect(screen.getByText('bold').tagName).toBe('STRONG')
    expect(screen.getByText('code').tagName).toBe('CODE')
    expect(screen.getByRole('link', { name: 'a source' }).getAttribute('href')).toBe('https://example.test/source')
    expect(screen.getByText(/\[S2\]/)).toBeTruthy()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('keeps raw HTML and unsafe Markdown links inert', () => {
    const { container } = render(<Markdown content={'<img src=x onerror=alert(1)> [run](javascript:alert(1))'} />)

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
  })

  it('renders fenced code as text without executing markup', () => {
    const { container } = render(<Markdown content={'```html\n<script>alert(1)</script>\n```'} />)

    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('pre code')?.textContent).toBe('<script>alert(1)</script>')
  })

  it('renders Markdown tables with semantic headers and cells', () => {
    render(<Markdown content={'| Metric | Goal |\n| --- | --- |\n| Activation | Improve |'} />)
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Metric' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'Activation' })).toBeInTheDocument()
  })
})
