/**
 * Tiny offline syntax highlighter for the Files editor.
 *
 * Why not highlight.js: the dashboard is served by the ESP32 itself and must
 * work with no internet (AP setup mode), so a CDN script is not an option and
 * the house test `test_no_external_fetches_in_the_ui` forbids it. Bundling
 * highlight.js would also add ~100-300 KB to a ~460 KB single-file bundle on
 * a microcontroller flash budget. This module is ~5 KB, dependency-free, and
 * covers exactly the extensions the Files editor opens.
 *
 * Usage: `highlightToHtml(source, path)` returns an HTML string with all
 * source text escaped and tokens wrapped in `<span class="tok-*">`. Render
 * it with `dangerouslySetInnerHTML` inside a `<pre class="code-view">`.
 * Only ever emits `tok-c | tok-s | tok-k | tok-n | tok-f` spans.
 */

export type LangId =
  | 'python'
  | 'javascript'
  | 'typescript'
  | 'json'
  | 'html'
  | 'css'
  | 'markdown'
  | 'yaml'
  | 'toml'
  | 'ini'
  | 'plain'

export function languageForPath(path: string): { id: LangId; label: string } {
  const m = /\.([A-Za-z0-9]+)$/.exec(path || '')
  const ext = (m ? m[1] : '').toLowerCase()
  switch (ext) {
    case 'py':
      return { id: 'python', label: 'Python' }
    case 'js':
      return { id: 'javascript', label: 'JavaScript' }
    case 'ts':
    case 'tsx':
      return { id: 'typescript', label: 'TypeScript' }
    case 'json':
    case 'jsonl':
      return { id: 'json', label: 'JSON' }
    case 'html':
    case 'htm':
    case 'svg':
      return { id: 'html', label: 'HTML' }
    case 'css':
      return { id: 'css', label: 'CSS' }
    case 'md':
      return { id: 'markdown', label: 'Markdown' }
    case 'yaml':
    case 'yml':
      return { id: 'yaml', label: 'YAML' }
    case 'toml':
      return { id: 'toml', label: 'TOML' }
    case 'ini':
    case 'cfg':
    case 'conf':
      return { id: 'ini', label: 'Config' }
    default:
      return { id: 'plain', label: 'Text' }
  }
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function isWordStart(ch: string): boolean {
  return /[A-Za-z_]/.test(ch)
}

function isWordChar(ch: string): boolean {
  return /[A-Za-z0-9_]/.test(ch)
}

const PY_KEYWORDS = new Set(
  'False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield'.split(
    ' ',
  ),
)

const JS_KEYWORDS = new Set(
  'await async break case catch class const continue debugger default delete do else export extends false finally for function if import in instanceof new null return super switch this throw true try typeof var void while with yield let static get set of from as'.split(
    ' ',
  ),
)

const JSON_LITERALS = new Set(['true', 'false', 'null'])
const YAML_LITERALS = new Set(['true', 'false', 'null', 'yes', 'no', 'on', 'off'])

/** Read a quoted string starting at `i` (src[i] is the quote). Handles `\` escapes. */
function readString(src: string, i: number, quote: string): number {
  let j = i + quote.length
  const n = src.length
  while (j < n) {
    if (src[j] === '\\') {
      j += 2
      continue
    }
    if (src.startsWith(quote, j)) return j + quote.length
    j += 1
  }
  return n
}

function readNumber(src: string, i: number): number {
  let j = i
  const n = src.length
  while (j < n && /[0-9a-fA-F_x.]/.test(src[j])) j += 1
  // unit suffixes: px, em, rem, %, ms, s, kb…
  while (j < n && /[a-zA-Z%]/.test(src[j])) {
    // stop before a fresh identifier (`123abc` is not a unit, bail instead)
    if (j - i > 16) break
    j += 1
  }
  return j
}

function readWord(src: string, i: number): number {
  let j = i
  while (j < src.length && isWordChar(src[j])) j += 1
  return j
}

function highlightPython(src: string): string {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    if (ch === '#') {
      let j = i
      while (j < n && src[j] !== '\n') j += 1
      out += `<span class="tok-c">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (src.startsWith('"""', i) || src.startsWith("'''", i)) {
      const q = src.slice(i, i + 3)
      const j = readString(src, i, q)
      out += `<span class="tok-s">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (ch === '"' || ch === "'") {
      const j = readString(src, i, ch)
      out += `<span class="tok-s">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (ch === '@' && i + 1 < n && /[A-Za-z_]/.test(src[i + 1])) {
      const j = readWord(src, i + 1)
      out += `<span class="tok-f">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (/[0-9]/.test(ch)) {
      const j = readNumber(src, i)
      out += `<span class="tok-n">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (isWordStart(ch)) {
      const j = readWord(src, i)
      const word = src.slice(i, j)
      if (PY_KEYWORDS.has(word)) {
        out += `<span class="tok-k">${esc(word)}</span>`
      } else if (src[j] === '(') {
        out += `<span class="tok-f">${esc(word)}</span>`
      } else {
        out += esc(word)
      }
      i = j
      continue
    }
    out += esc(ch)
    i += 1
  }
  return out
}

function highlightCStyle(src: string, keywords: Set<string>): string {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    if (src.startsWith('//', i)) {
      let j = i
      while (j < n && src[j] !== '\n') j += 1
      out += `<span class="tok-c">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (src.startsWith('/*', i)) {
      const end = src.indexOf('*/', i + 2)
      const j = end === -1 ? n : end + 2
      out += `<span class="tok-c">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    const ch = src[i]
    if (ch === '"' || ch === "'" || ch === '`') {
      const j = readString(src, i, ch)
      out += `<span class="tok-s">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (/[0-9]/.test(ch)) {
      const j = readNumber(src, i)
      out += `<span class="tok-n">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (isWordStart(ch) || ch === '$') {
      const j = readWord(src, i + (ch === '$' ? 1 : 0))
      const word = src.slice(i, j)
      if (keywords.has(word)) {
        out += `<span class="tok-k">${esc(word)}</span>`
      } else if (src[j] === '(') {
        out += `<span class="tok-f">${esc(word)}</span>`
      } else {
        out += esc(word)
      }
      i = j
      continue
    }
    out += esc(ch)
    i += 1
  }
  return out
}

function highlightJson(src: string): string {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    if (ch === '"' || ch === "'") {
      const j = readString(src, i, ch)
      // A string followed by `:` is an object key.
      let k = j
      while (k < n && /[ \t]/.test(src[k])) k += 1
      const cls = src[k] === ':' ? 'tok-f' : 'tok-s'
      out += `<span class="${cls}">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (ch === '-' || /[0-9]/.test(ch)) {
      const j = readNumber(src, i)
      out += `<span class="tok-n">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (isWordStart(ch)) {
      const j = readWord(src, i)
      const word = src.slice(i, j)
      if (JSON_LITERALS.has(word)) out += `<span class="tok-k">${esc(word)}</span>`
      else out += esc(word)
      i = j
      continue
    }
    out += esc(ch)
    i += 1
  }
  return out
}

function highlightYamlToml(src: string): string {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const lineStart = i === 0 || src[i - 1] === '\n'
    const ch = src[i]
    if (ch === '#') {
      let j = i
      while (j < n && src[j] !== '\n') j += 1
      out += `<span class="tok-c">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (ch === '"' || ch === "'") {
      const j = readString(src, i, ch)
      out += `<span class="tok-s">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (lineStart && (isWordStart(ch) || ch === '[' || ch === '-' || ch === '?' || ch === ' ' || ch === '\t')) {
      // Key at line start: `key:`, `key =`, `[section]`, `- item`.
      // Leading whitespace is allowed: indented `  key:` is the norm.
      let j = i
      while (j < n && src[j] !== '\n') j += 1
      const line = src.slice(i, j)
      const m = /^(\s*(?:-\s+)?)([A-Za-z0-9_./-]+)(\s*[:=])/.exec(line)
      if (m) {
        const keyEnd = m[1].length + m[2].length
        out += esc(line.slice(0, m[1].length))
        out += `<span class="tok-f">${esc(m[2])}</span>`
        // Recurse on the value half so strings/numbers/comments highlight.
        const rest = line.slice(keyEnd)
        out += highlightYamlValue(rest)
        i = j
        continue
      }
      if (/^\s*\[[^\]\n]*\]/.test(line)) {
        out += `<span class="tok-k">${esc(line)}</span>`
        i = j
        continue
      }
    }
    if (/[0-9]/.test(ch) && (i === 0 || /[\s:=\[,{]/.test(src[i - 1]))) {
      const j = readNumber(src, i)
      out += `<span class="tok-n">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (isWordStart(ch)) {
      const j = readWord(src, i)
      const word = src.slice(i, j)
      if (YAML_LITERALS.has(word)) out += `<span class="tok-k">${esc(word)}</span>`
      else out += esc(word)
      i = j
      continue
    }
    out += esc(ch)
    i += 1
  }
  return out
}

/** Highlight the value half of a `key: value` line (strings, numbers, literals). */
function highlightYamlValue(frag: string): string {
  let out = ''
  let i = 0
  const n = frag.length
  while (i < n) {
    const ch = frag[i]
    if (ch === '#') {
      out += `<span class="tok-c">${esc(frag.slice(i))}</span>`
      break
    }
    if (ch === '"' || ch === "'") {
      const j = readString(frag, i, ch)
      out += `<span class="tok-s">${esc(frag.slice(i, j))}</span>`
      i = j
      continue
    }
    if (/[0-9]/.test(ch) && (i === 0 || /[\s:=\[,{]/.test(frag[i - 1]))) {
      const j = readNumber(frag, i)
      out += `<span class="tok-n">${esc(frag.slice(i, j))}</span>`
      i = j
      continue
    }
    if (isWordStart(ch)) {
      const j = readWord(frag, i)
      const word = frag.slice(i, j)
      if (YAML_LITERALS.has(word)) out += `<span class="tok-k">${esc(word)}</span>`
      else out += esc(word)
      i = j
      continue
    }
    out += esc(ch)
    i += 1
  }
  return out
}

function highlightIni(src: string): string {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    if (ch === '#' || ch === ';') {
      let j = i
      while (j < n && src[j] !== '\n') j += 1
      out += `<span class="tok-c">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (ch === '"' || ch === "'") {
      const j = readString(src, i, ch)
      out += `<span class="tok-s">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (ch === '[') {
      const j = src.indexOf('\n', i)
      const end = j === -1 ? n : j
      const close = src.indexOf(']', i)
      if (close !== -1 && close < end) {
        out += `<span class="tok-k">${esc(src.slice(i, close + 1))}</span>`
        i = close + 1
        continue
      }
    }
    const lineStart = i === 0 || src[i - 1] === '\n'
    if (lineStart && (isWordStart(ch) || ch === '.' || ch === ' ' || ch === '\t')) {
      let j = i
      while (j < n && src[j] !== '\n') j += 1
      const line = src.slice(i, j)
      const m = /^(\s*)([A-Za-z0-9_.-]+)(\s*[:=])/.exec(line)
      if (m) {
        out += esc(m[1])
        out += `<span class="tok-f">${esc(m[2])}</span>`
        out += esc(line.slice(m[1].length + m[2].length))
        i = j
        continue
      }
    }
    out += esc(ch)
    i += 1
  }
  return out
}

function highlightHtml(src: string): string {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    if (src.startsWith('<!--', i)) {
      const end = src.indexOf('-->', i + 4)
      const j = end === -1 ? n : end + 3
      out += `<span class="tok-c">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (src[i] === '<' && i + 1 < n && /[A-Za-z/!?]/.test(src[i + 1])) {
      // Tag open: highlight `<`, `tag`, then attrs/strings until `>`.
      out += esc('<')
      i += 1
      if (src[i] === '/') {
        out += esc('/')
        i += 1
      }
      const j = readWord(src, i)
      if (j > i) {
        out += `<span class="tok-k">${esc(src.slice(i, j))}</span>`
        i = j
      }
      while (i < n && src[i] !== '>' && src[i] !== '\n') {
        if (src.startsWith('/>', i)) {
          out += esc('/>')
          i += 2
          break
        }
        const ch = src[i]
        if (ch === '"' || ch === "'") {
          const k = readString(src, i, ch)
          out += `<span class="tok-s">${esc(src.slice(i, k))}</span>`
          i = k
          continue
        }
        if (/[0-9]/.test(ch)) {
          const k = readNumber(src, i)
          out += `<span class="tok-n">${esc(src.slice(i, k))}</span>`
          i = k
          continue
        }
        if (isWordStart(ch) || ch === '-' || ch === ':') {
          let k = i
          while (k < n && /[A-Za-z0-9_.:-]/.test(src[k])) k += 1
          let m = k
          while (m < n && src[m] === ' ') m += 1
          if (src[m] === '=') {
            out += `<span class="tok-f">${esc(src.slice(i, k))}</span>`
            i = k
            continue
          }
          out += esc(src.slice(i, k))
          i = k
          continue
        }
        out += esc(ch)
        i += 1
      }
      continue
    }
    if (src[i] === '&' && /^&[A-Za-z0-9#]+;/.test(src.slice(i, i + 10))) {
      const m = /^&[A-Za-z0-9#]+;/.exec(src.slice(i, i + 10))
      const ent = m ? m[0] : '&'
      out += `<span class="tok-n">${esc(ent)}</span>`
      i += ent.length
      continue
    }
    out += esc(src[i])
    i += 1
  }
  return out
}

function highlightCss(src: string): string {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    if (src.startsWith('/*', i)) {
      const end = src.indexOf('*/', i + 2)
      const j = end === -1 ? n : end + 2
      out += `<span class="tok-c">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    const ch = src[i]
    if (ch === '"' || ch === "'") {
      const j = readString(src, i, ch)
      out += `<span class="tok-s">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (ch === '@') {
      const j = readWord(src, i + 1)
      out += `<span class="tok-k">${esc(src.slice(i, Math.max(j, i + 1)))}</span>`
      i = Math.max(j, i + 1)
      continue
    }
    if (ch === '#' && i + 1 < n && /[0-9A-Fa-f]/.test(src[i + 1])) {
      let j = i + 1
      while (j < n && j - i <= 7 && /[0-9A-Fa-f]/.test(src[j])) j += 1
      out += `<span class="tok-n">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (/[0-9]/.test(ch) || (ch === '.' && i + 1 < n && /[0-9]/.test(src[i + 1]))) {
      const j = readNumber(src, i)
      out += `<span class="tok-n">${esc(src.slice(i, j))}</span>`
      i = j
      continue
    }
    if (isWordStart(ch) || ch === '-' || ch === '.') {
      let j = i
      while (j < n && /[A-Za-z0-9_.-]/.test(src[j])) j += 1
      if (j === i) {
        out += esc(ch)
        i += 1
        continue
      }
      let k = j
      while (k < n && src[k] === ' ') k += 1
      const word = src.slice(i, j)
      if (src[k] === ':' && word[0] !== '.') {
        out += `<span class="tok-f">${esc(word)}</span>`
      } else if (src[k] === '(') {
        out += `<span class="tok-k">${esc(word)}</span>`
      } else {
        out += esc(word)
      }
      i = j
      continue
    }
    out += esc(ch)
    i += 1
  }
  return out
}

function highlightMarkdown(src: string): string {
  // Line structure first (headings, quotes, lists), then inline spans.
  const lines = src.split('\n')
  return lines
    .map((line) => highlightMarkdownLine(line))
    .join('\n')
}

function highlightMarkdownLine(line: string): string {
  const heading = /^(#{1,6}\s+)(.*)$/.exec(line)
  if (heading) {
    return `<span class="tok-k">${esc(heading[1])}</span>${highlightMarkdownInline(heading[2])}`
  }
  const quote = /^(&gt;|>)\s?(.*)$/.exec(line)
  if (quote) {
    return `<span class="tok-c">${esc(line.slice(0, line.length - quote[2].length))}</span>${highlightMarkdownInline(quote[2])}`
  }
  const fence = /^(```|~~~)(.*)$/.exec(line)
  if (fence) return `<span class="tok-k">${esc(fence[1])}</span><span class="tok-f">${esc(fence[2])}</span>`
  const list = /^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$/.exec(line)
  if (list) {
    return `<span class="tok-k">${esc(list[1])}</span>${highlightMarkdownInline(list[2])}`
  }
  return highlightMarkdownInline(line)
}

function highlightMarkdownInline(frag: string): string {
  let out = ''
  let i = 0
  const n = frag.length
  while (i < n) {
    if (frag[i] === '`') {
      const end = frag.indexOf('`', i + 1)
      const j = end === -1 ? n : end + 1
      out += `<span class="tok-s">${esc(frag.slice(i, j))}</span>`
      i = j
      continue
    }
    if (frag.startsWith('**', i) || frag.startsWith('__', i)) {
      const mark = frag.slice(i, i + 2)
      const end = frag.indexOf(mark, i + 2)
      const j = end === -1 ? i + 2 : end + 2
      out += `<span class="tok-f">${esc(frag.slice(i, j))}</span>`
      i = j
      continue
    }
    if (frag[i] === '[') {
      const mid = frag.indexOf('](', i + 1)
      if (mid !== -1) {
        const close = frag.indexOf(')', mid + 2)
        if (close !== -1) {
          out += `<span class="tok-f">${esc(frag.slice(i, mid + 1))}</span>`
          out += `<span class="tok-s">${esc(frag.slice(mid + 1, close + 1))}</span>`
          i = close + 1
          continue
        }
      }
    }
    out += esc(frag[i])
    i += 1
  }
  return out
}

/**
 * Highlight `source` for display. The file extension picks the grammar;
 * unknown extensions render as escaped plain text. Output is always safe
 * to inject: every source byte passes through `esc()`.
 */
export function highlightToHtml(source: string, path: string): string {
  const { id } = languageForPath(path)
  switch (id) {
    case 'python':
      return highlightPython(source)
    case 'javascript':
      return highlightCStyle(source, JS_KEYWORDS)
    case 'typescript':
      return highlightCStyle(source, JS_KEYWORDS)
    case 'json':
      return highlightJson(source)
    case 'html':
      return highlightHtml(source)
    case 'css':
      return highlightCss(source)
    case 'markdown':
      return highlightMarkdown(source)
    case 'yaml':
    case 'toml':
      return highlightYamlToml(source)
    case 'ini':
      return highlightIni(source)
    default:
      return esc(source)
  }
}
