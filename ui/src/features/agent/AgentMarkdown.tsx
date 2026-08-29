import { Fragment, type ReactNode } from 'react'

interface AgentMarkdownProps {
  text: string
}

const INLINE_TOKEN = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\)|\*[^*\n]+\*|_[^_\n]+_)/g

function safeLink(value: string): string | null {
  try {
    const url = new URL(value, window.location.origin)
    return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? url.href : null
  } catch {
    return null
  }
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let cursor = 0
  let index = 0
  for (const match of text.matchAll(INLINE_TOKEN)) {
    const start = match.index ?? 0
    if (start > cursor) nodes.push(text.slice(cursor, start))
    const token = match[0]
    const key = `${keyPrefix}-${index++}`
    if ((token.startsWith('**') && token.endsWith('**')) || (token.startsWith('__') && token.endsWith('__'))) {
      nodes.push(<strong key={key}>{renderInline(token.slice(2, -2), `${key}-strong`)}</strong>)
    } else if (token.startsWith('`') && token.endsWith('`')) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>)
    } else if (token.startsWith('[')) {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
      const href = link ? safeLink(link[2]) : null
      nodes.push(href && link
        ? <a key={key} href={href} target="_blank" rel="noreferrer">{link[1]}</a>
        : <Fragment key={key}>{token}</Fragment>)
    } else {
      nodes.push(<em key={key}>{renderInline(token.slice(1, -1), `${key}-em`)}</em>)
    }
    cursor = start + token.length
  }
  if (cursor < text.length) nodes.push(text.slice(cursor))
  return nodes
}

function isBlockStart(line: string): boolean {
  return /^\s*(?:```|#{1,4}\s+|>\s?|[-+*]\s+|\d+\.\s+)/.test(line)
}

export function AgentMarkdown({ text }: AgentMarkdownProps) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let cursor = 0
  let key = 0

  while (cursor < lines.length) {
    const line = lines[cursor]
    if (!line.trim()) {
      cursor += 1
      continue
    }

    const fence = line.match(/^\s*```([^\s`]*)\s*$/)
    if (fence) {
      const code: string[] = []
      cursor += 1
      while (cursor < lines.length && !/^\s*```\s*$/.test(lines[cursor])) {
        code.push(lines[cursor])
        cursor += 1
      }
      if (cursor < lines.length) cursor += 1
      blocks.push(<pre key={`block-${key++}`}><code data-language={fence[1] || undefined}>{code.join('\n')}</code></pre>)
      continue
    }

    const heading = line.match(/^\s*(#{1,4})\s+(.+)$/)
    if (heading) {
      const content = renderInline(heading[2], `heading-${key}`)
      const headingKey = `block-${key++}`
      if (heading[1].length === 1) blocks.push(<h2 key={headingKey}>{content}</h2>)
      else if (heading[1].length === 2) blocks.push(<h3 key={headingKey}>{content}</h3>)
      else blocks.push(<h4 key={headingKey}>{content}</h4>)
      cursor += 1
      continue
    }

    const unordered = line.match(/^\s*[-+*]\s+(.+)$/)
    if (unordered) {
      const items: string[] = []
      while (cursor < lines.length) {
        const item = lines[cursor].match(/^\s*[-+*]\s+(.+)$/)
        if (!item) break
        items.push(item[1])
        cursor += 1
      }
      blocks.push(
        <ul key={`block-${key++}`}>
          {items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item, `ul-${key}-${itemIndex}`)}</li>)}
        </ul>,
      )
      continue
    }

    const ordered = line.match(/^\s*(\d+)\.\s+(.+)$/)
    if (ordered) {
      const start = Number(ordered[1])
      const items: string[] = []
      while (cursor < lines.length) {
        const item = lines[cursor].match(/^\s*\d+\.\s+(.+)$/)
        if (!item) break
        items.push(item[1])
        cursor += 1
      }
      blocks.push(
        <ol key={`block-${key++}`} start={start}>
          {items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item, `ol-${key}-${itemIndex}`)}</li>)}
        </ol>,
      )
      continue
    }

    if (/^\s*>/.test(line)) {
      const quote: string[] = []
      while (cursor < lines.length) {
        const item = lines[cursor].match(/^\s*>\s?(.*)$/)
        if (!item) break
        quote.push(item[1])
        cursor += 1
      }
      blocks.push(<blockquote key={`block-${key++}`}>{renderInline(quote.join('\n'), `quote-${key}`)}</blockquote>)
      continue
    }

    const paragraph = [line.trim()]
    cursor += 1
    while (cursor < lines.length && lines[cursor].trim() && !isBlockStart(lines[cursor])) {
      paragraph.push(lines[cursor].trim())
      cursor += 1
    }
    blocks.push(<p key={`block-${key++}`}>{renderInline(paragraph.join('\n'), `paragraph-${key}`)}</p>)
  }

  return <div className="hp-agent-markdown">{blocks}</div>
}
