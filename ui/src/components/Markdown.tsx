import { useMemo } from 'react'
import { cn } from '@/lib/utils'

/**
 * Dependency-free markdown renderer.
 *
 * The upstream dashboard pulls a full markdown library; here every kilobyte
 * of JS is flash on a microcontroller, so this handles the subset an LLM
 * actually emits: fenced code, headings, lists, quotes, inline code, bold,
 * italic and links. Input is escaped first — formatting is applied to the
 * escaped text, so model output can never inject markup.
 */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inline(text: string): string {
  let out = text
  // inline code first so `**` inside code is not treated as bold
  const codes: string[] = []
  out = out.replace(/`([^`\n]+)`/g, (_m, code: string) => {
    codes.push(code)
    return `\u0000${codes.length - 1}\u0000`
  })
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  out = out.replace(/(^|[\s(])_([^_\n]+)_/g, '$1<em>$2</em>')
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  )
  out = out.replace(/\u0000(\d+)\u0000/g, (_m, i: string) => `<code>${codes[Number(i)] ?? ''}</code>`)
  return out
}

function render(source: string): string {
  const lines = escapeHtml(source.replace(/\r\n/g, '\n')).split('\n')
  const html: string[] = []
  let i = 0
  let listType: 'ul' | 'ol' | null = null

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`)
      listType = null
    }
  }

  while (i < lines.length) {
    const line = lines[i]

    // fenced code
    const fence = line.match(/^\s*```(\w*)\s*$/)
    if (fence) {
      closeList()
      const lang = fence[1]
      const body: string[] = []
      i += 1
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        body.push(lines[i])
        i += 1
      }
      i += 1
      html.push(
        `<pre>${lang ? `<div class="mb-1 text-[0.6rem] uppercase tracking-[0.14em] text-text-faint">${lang}</div>` : ''}<code>${body.join('\n')}</code></pre>`,
      )
      continue
    }

    if (!line.trim()) {
      closeList()
      i += 1
      continue
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    if (heading) {
      closeList()
      const level = Math.min(3, heading[1].length)
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`)
      i += 1
      continue
    }

    if (/^&gt;\s?/.test(line)) {
      closeList()
      const quote: string[] = []
      while (i < lines.length && /^&gt;\s?/.test(lines[i])) {
        quote.push(lines[i].replace(/^&gt;\s?/, ''))
        i += 1
      }
      html.push(`<blockquote>${inline(quote.join(' '))}</blockquote>`)
      continue
    }

    const bullet = line.match(/^\s*[-*+]\s+(.*)$/)
    if (bullet) {
      if (listType !== 'ul') {
        closeList()
        html.push('<ul>')
        listType = 'ul'
      }
      html.push(`<li>${inline(bullet[1])}</li>`)
      i += 1
      continue
    }

    const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (ordered) {
      if (listType !== 'ol') {
        closeList()
        html.push('<ol>')
        listType = 'ol'
      }
      html.push(`<li>${inline(ordered[1])}</li>`)
      i += 1
      continue
    }

    closeList()
    const para: string[] = [line]
    i += 1
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*```/.test(lines[i]) &&
      !/^(#{1,4})\s+/.test(lines[i]) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+[.)]\s+/.test(lines[i]) &&
      !/^&gt;\s?/.test(lines[i])
    ) {
      para.push(lines[i])
      i += 1
    }
    html.push(`<p>${inline(para.join(' '))}</p>`)
  }
  closeList()
  return html.join('')
}

export function Markdown({ source, className }: { source: string; className?: string }) {
  const html = useMemo(() => render(source), [source])
  return <div className={cn('md', className)} dangerouslySetInnerHTML={{ __html: html }} />
}
