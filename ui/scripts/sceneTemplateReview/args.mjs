import path from 'node:path'
import { parsePort, validateListenHost, LOOPBACK_HOST } from './server.mjs'

export function usage() {
  return `Usage: tsx scripts/scene-template-review.mjs [--render [--assets plan.json]] [--showcase-dir DIR] [--host 192.168.x.x] [--port N] [template-id ...]

Builds the actual UI into a temporary directory and serves a provider-free review sandbox.
The default bind is loopback on an ephemeral port; --host may expose the same server on
one RFC1918 address present on a local interface. Every run writes only to a fresh
directory under the operating system temporary directory. --showcase-dir loads a local
manifest.json plus its explicitly referenced media and canonical image inputs before the
server indexes the UI; no network or video generator is used.

--render renders every card in the catalog (or the given IDs) to an MP4, a poster, a 3x2
contact sheet and a metadata JSON per card, plus one review.json index. Without --assets
the cards use the catalog's inline demo art. --assets maps slot names (subject_1,
subject_2, background, prop_1, prop_2, foreground; hero, plate and prop are read too) to
local pictures, GLBs or videos, as {slot: file} for every card or as
{"default": {...}, "families": {"music": {...}}, "cards": {"<id>": {..., "controls": {...}}}}.
`
}

/** `env.INIT_CWD` is the folder npm was started from; --assets resolves from there. */
export function parseArgs(argv, env = process.env) {
  let render = false
  let host = LOOPBACK_HOST
  let port = 0
  let showcaseDir = null
  let assetsFile = null
  const templateIds = []
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    if (argument === '--help' || argument === '-h') return { help: true }
    if (argument === '--render') { render = true; continue }
    if (argument === '--showcase-dir') {
      const value = argv[index + 1]
      if (!value || value.startsWith('--')) throw new Error(`${argument} needs a value.`)
      index += 1
      showcaseDir = value
      continue
    }
    if (argument === '--assets') {
      const value = argv[index + 1]
      if (!value || value.startsWith('--')) throw new Error(`${argument} needs a value.`)
      index += 1
      assetsFile = value
      continue
    }
    if (argument.startsWith('--assets=')) {
      assetsFile = argument.slice('--assets='.length)
      if (!assetsFile) throw new Error('--assets needs a value.')
      continue
    }
    if (argument === '--host' || argument === '--port') {
      const value = argv[index + 1]
      if (!value || value.startsWith('--')) throw new Error(`${argument} needs a value.`)
      index += 1
      if (argument === '--host') host = value
      else port = parsePort(value)
      continue
    }
    if (argument.startsWith('--host=')) { host = argument.slice('--host='.length); continue }
    if (argument.startsWith('--port=')) { port = parsePort(argument.slice('--port='.length)); continue }
    if (argument.startsWith('--showcase-dir=')) {
      const value = argument.slice('--showcase-dir='.length)
      if (!value) throw new Error('--showcase-dir needs a value.')
      showcaseDir = value
      continue
    }
    if (argument.startsWith('--')) throw new Error(`Unknown option “${argument}”.`)
    templateIds.push(argument)
  }
  if (templateIds.length && !render) throw new Error('Template IDs require --render.')
  if (assetsFile && !render) throw new Error('--assets requires --render.')
  validateListenHost(host)
  return {
    render, host, port, templateIds,
    showcaseDir: showcaseDir ? path.resolve(process.cwd(), showcaseDir) : null,
    // npm runs scripts from ui/; INIT_CWD is where the user typed the command.
    assetsFile: assetsFile ? path.resolve(env.INIT_CWD || process.cwd(), assetsFile) : null,
  }
}
