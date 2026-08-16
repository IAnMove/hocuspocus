import { readdir, readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const dist = resolve(dirname(fileURLToPath(import.meta.url)), '../dist')
const assetsDir = resolve(dist, 'assets')
const ENTRY_JS_GZIP_BUDGET = 320 * 1024

const assets = (await readdir(assetsDir))
  .filter(name => name.endsWith('.js') || name.endsWith('.css'))
  .sort()

const entrypoints = assets.filter(name => /^index-[^/]+\.js$/.test(name))
if (entrypoints.length !== 1) {
  throw new Error(`Expected exactly one Vite entry JS asset, found: ${entrypoints.join(', ') || 'none'}`)
}
const directorChunks = assets.filter(name => /^DirectorDashboard-[^/]+\.js$/.test(name))
if (directorChunks.length !== 1) {
  throw new Error(`DirectorDashboard must remain one lazy chunk, found: ${directorChunks.join(', ') || 'none'}`)
}

const measurements = await Promise.all(assets.map(async name => {
  const bytes = await readFile(resolve(assetsDir, name))
  return { name, bytes: bytes.byteLength, gzip: gzipSync(bytes).byteLength }
}))

for (const measurement of measurements) {
  console.log(`${measurement.name}\t${measurement.bytes} B\tgzip ${measurement.gzip} B`)
}

const entrypoint = measurements.find(measurement => measurement.name === entrypoints[0])
if (!entrypoint) throw new Error(`Missing measurement for ${entrypoints[0]}`)
console.log(`Entry JS gzip: ${entrypoint.gzip} B / ${ENTRY_JS_GZIP_BUDGET} B budget`)

if (entrypoint.gzip > ENTRY_JS_GZIP_BUDGET) {
  throw new Error(`Entry JS gzip budget exceeded by ${entrypoint.gzip - ENTRY_JS_GZIP_BUDGET} B`)
}
