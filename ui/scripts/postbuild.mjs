// Post-build: stamp the bundle URL with a content hash and emit gzip twins.
//
// `assets/app.js` and `assets/app.css` keep stable names so the ESP32 only
// ever stores two files, but stable names cache badly. Appending `?v=<hash>`
// gives each build a distinct URL, which lets the device serve assets as
// immutable — a returning browser re-uses them instead of pulling 440 KB off
// the microcontroller's flash on every page load.
//
// The `.gz` twins matter more than they look: MicroPython has no compression
// of its own, so serving a pre-compressed file turns a ~7 s build load into
// ~2 s on the same flash.
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { gzipSync } from 'node:zlib'
import { join } from 'node:path'

const outDir = process.argv[2] || '../www'
const indexPath = join(outDir, 'index.html')

const js = await readFile(join(outDir, 'assets', 'app.js'))
const css = await readFile(join(outDir, 'assets', 'app.css')).catch(() => null)

const hash = createHash('sha256').update(js)
if (css) hash.update(css)
const version = hash.digest('hex').slice(0, 10)

let html = await readFile(indexPath, 'utf8')
html = html
  .replace(/(src="\/assets\/app\.js)(")/, `$1?v=${version}$2`)
  .replace(/(href="\/assets\/app\.css)(")/, `$1?v=${version}$2`)

await writeFile(indexPath, html)

const gzJs = gzipSync(js, { level: 9 })
await writeFile(join(outDir, 'assets', 'app.js.gz'), gzJs)

let gzCss = null
if (css) {
  gzCss = gzipSync(css, { level: 9 })
  await writeFile(join(outDir, 'assets', 'app.css.gz'), gzCss)
}

const kb = (buffer) => (buffer.length / 1024).toFixed(1)
console.log(`stamped build ${version}`)
console.log(`  index.html   ${kb(Buffer.from(html))} kB`)
console.log(`  app.js       ${kb(js)} kB  -> gz ${kb(gzJs)} kB`)
if (css) console.log(`  app.css      ${kb(css)} kB  -> gz ${kb(gzCss)} kB`)
console.log(`  wire total   ${kb(Buffer.concat([gzJs, gzCss ?? Buffer.alloc(0)]))} kB (gzip)`)

