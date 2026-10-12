import type { ReactNode } from 'react'
import { safeExternalUrl } from '../utils/safeUrl'

const inlineToken = /(\[[^\]]+\]\(https?:\/\/[^\s)]+(?:\s+"[^"]*")?\)|`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|~~[^~]+~~)/g

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  return text.split(inlineToken).filter(Boolean).map((token, index) => {
    const key = `${keyPrefix}-${index}`
    const link = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)(?:\s+"[^"]*")?\)$/)
    if (link) {
      const url = safeExternalUrl(link[2])
      return url
        ? <a key={key} href={url} target="_blank" rel="noreferrer">{link[1]}</a>
        : link[1]
    }
    if (token.startsWith('`') && token.endsWith('`')) return <code key={key}>{token.slice(1, -1)}</code>
    if ((token.startsWith('**') && token.endsWith('**')) || (token.startsWith('__') && token.endsWith('__'))) {
      return <strong key={key}>{token.slice(2, -2)}</strong>
    }
    if (token.startsWith('~~') && token.endsWith('~~')) return <del key={key}>{token.slice(2, -2)}</del>
    if ((token.startsWith('*') && token.endsWith('*')) || (token.startsWith('_') && token.endsWith('_'))) {
      return <em key={key}>{token.slice(1, -1)}</em>
    }
    return token
  })
}

function isBlockStart(line: string): boolean {
  return /^#{1,6}\s|^```|^\s*[-*+]\s+|^\s*\d+[.)]\s+|^>\s?/.test(line)
}

/** Render the supported Markdown subset as React elements; raw HTML stays inert text. */
export function Markdown({ content, className }: { content: string; className?: string }) {
  const lines = content.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) { index += 1; continue }

    if (/^\s*```/.test(line)) {
      const code: string[] = []
      index += 1
      while (index < lines.length && !/^\s*```/.test(lines[index])) code.push(lines[index++])
      if (index < lines.length) index += 1
      blocks.push(<pre key={`code-${blocks.length}`}><code>{code.join('\n')}</code></pre>)
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+?)\s*#*$/)
    if (heading) {
      const level = heading[1].length
      const children = renderInline(heading[2], `heading-${index}`)
      const key = `heading-${index}`
      if (level === 1) blocks.push(<h1 key={key}>{children}</h1>)
      else if (level === 2) blocks.push(<h2 key={key}>{children}</h2>)
      else if (level === 3) blocks.push(<h3 key={key}>{children}</h3>)
      else if (level === 4) blocks.push(<h4 key={key}>{children}</h4>)
      else if (level === 5) blocks.push(<h5 key={key}>{children}</h5>)
      else blocks.push(<h6 key={key}>{children}</h6>)
      index += 1
      continue
    }

    const listItem = line.match(/^\s*([-*+]|\d+[.)])\s+(.+)$/)
    if (listItem) {
      const ordered = /^\d/.test(listItem[1])
      const items: ReactNode[] = []
      while (index < lines.length) {
        const item = lines[index].match(/^\s*([-*+]|\d+[.)])\s+(.+)$/)
        if (!item || /^\d/.test(item[1]) !== ordered) break
        items.push(<li key={`item-${index}`}>{renderInline(item[2], `item-${index}`)}</li>)
        index += 1
      }
      blocks.push(ordered ? <ol key={`list-${index}`}>{items}</ol> : <ul key={`list-${index}`}>{items}</ul>)
      continue
    }

    if (/^>\s?/.test(line)) {
      const quote: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index])) quote.push(lines[index++].replace(/^>\s?/, ''))
      blocks.push(<blockquote key={`quote-${index}`}>{renderInline(quote.join(' '), `quote-${index}`)}</blockquote>)
      continue
    }

    if (line.includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])) {
      const cells = (row: string) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim())
      const headers = cells(line)
      index += 2
      const rows: string[][] = []
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) rows.push(cells(lines[index++]))
      blocks.push(<div className="markdown-table-wrap" key={`table-${index}`}><table><thead><tr>{headers.map((cell, column) => <th key={column}>{renderInline(cell, `table-head-${index}-${column}`)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, column) => <td key={column}>{renderInline(row[column] ?? '', `table-cell-${index}-${rowIndex}-${column}`)}</td>)}</tr>)}</tbody></table></div>)
      continue
    }

    const paragraph: string[] = []
    while (index < lines.length && lines[index].trim() && (paragraph.length === 0 || !isBlockStart(lines[index]))) {
      paragraph.push(lines[index++])
    }
    blocks.push(<p key={`paragraph-${index}`}>{renderInline(paragraph.join(' '), `paragraph-${index}`)}</p>)
  }

  return <div className={className}>{blocks}</div>
}
