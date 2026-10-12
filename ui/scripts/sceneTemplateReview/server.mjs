import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import fs from 'node:fs/promises'
import { createReadStream } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { createWriteBudget, REVIEW_HEADERS, validateReviewSnapshot } from './security.mjs'

const MAX_REQUEST_BYTES = 40 * 1024 * 1024
const MAX_BLOCKED_REQUESTS = 128
const MAX_INPUTS = 64
const MAX_INPUT_FILE_BYTES = 4 * 1024 * 1024
/** A GLB or a looping video background is bigger than a picture. */
const MAX_MEDIA_INPUT_FILE_BYTES = 32 * 1024 * 1024
const MAX_INPUT_BYTES = 128 * 1024 * 1024
const LOOPBACK_HOST = '127.0.0.1'
const PREVIEW_PATH = /^\/scene-template-previews\/([a-z0-9][a-z0-9-]*(?:\.failure-[0-9a-f-]+|\.sheet)?)\.(mp4|png|json)$/
const SAFE_INPUT_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.(?:jpe?g|png|webp|glb|mp4|webm)$/i
const MEDIA_INPUT = /\.(?:glb|mp4|webm)$/i
class RequestTooLargeError extends Error {}

const json = (response, value, status = 200) => {
  const bytes = Buffer.from(JSON.stringify(value))
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': bytes.length,
    'cache-control': 'no-store',
  })
  response.end(bytes)
}

const isPrivateIpv4 = value => {
  const octets = value.split('.').map(Number)
  if (octets.length !== 4 || octets.some(octet => !Number.isInteger(octet) || octet < 0 || octet > 255)) return false
  return octets[0] === 10
    || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31)
    || (octets[0] === 192 && octets[1] === 168)
}

const localIpv4Addresses = () => new Set(Object.values(os.networkInterfaces())
  .flatMap(entries => entries || [])
  .filter(entry => entry.family === 'IPv4' || entry.family === 4)
  .map(entry => entry.address))

export function validateListenHost(host) {
  if (host === LOOPBACK_HOST) return host
  if (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(host) || !isPrivateIpv4(host)) {
    throw new Error(`--host must be 127.0.0.1 or a local RFC1918 IPv4 address; refused “${host}”.`)
  }
  if (!localIpv4Addresses().has(host)) {
    throw new Error(`--host ${host} is not present on a local network interface.`)
  }
  return host
}

export function parsePort(value) {
  if (value === undefined || value === null || String(value).trim() === '') throw new Error('Missing --port value.')
  const port = Number(value)
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error(`Invalid --port “${value}”; use an integer from 0 to 65535.`)
  return port
}

async function readBody(request) {
  const chunks = []
  let size = 0
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
    size += buffer.length
    if (size > MAX_REQUEST_BYTES) throw new RequestTooLargeError('Review sandbox request exceeds the 40 MB limit.')
    chunks.push(buffer)
  }
  return Buffer.concat(chunks)
}

const MIME_TYPES = {
  '.mp4': 'video/mp4', '.webm': 'video/webm', '.glb': 'model/gltf-binary', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.png': 'image/png', '.webp': 'image/webp', '.svg': 'image/svg+xml',
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.wasm': 'application/wasm',
}
const contentType = filename => MIME_TYPES[path.extname(filename).toLowerCase()] || 'application/octet-stream'

function validateInputName(name) {
  if (typeof name !== 'string' || !SAFE_INPUT_NAME.test(name)
    || name.includes('/') || name.includes('\\') || name === '.' || name === '..') {
    throw new Error('Input name must be a safe JPG, JPEG, PNG, WebP, GLB, MP4 or WebM basename.')
  }
  return name
}

async function indexStaticUi(root) {
  const files = new Map()
  if (!root) return files // HTTP contract tests need no UI build or browser.
  const visit = async directory => {
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      const filename = path.join(directory, entry.name)
      if (entry.isDirectory()) await visit(filename)
      else if (entry.isFile()) files.set('/' + path.relative(root, filename).split(path.sep).join('/'), filename)
    }
  }
  await visit(root)
  return files
}

async function sendFile(request, response, filename) {
  const stat = await fs.stat(filename)
  const range = request.headers.range?.match(/^bytes=(\d+)-(\d*)$/)
  if (request.headers.range && !range) {
    response.writeHead(416, { 'content-range': `bytes */${stat.size}` })
    response.end()
    return
  }
  const baseHeaders = { 'content-type': contentType(filename), 'accept-ranges': 'bytes', 'cache-control': 'no-store' }
  if (!range) {
    response.writeHead(200, { ...baseHeaders, 'content-length': stat.size })
    if (request.method === 'HEAD') response.end()
    else createReadStream(filename).on('error', () => response.destroy()).pipe(response)
    return
  }
  const start = Number(range[1])
  const end = Math.min(stat.size - 1, range[2] ? Number(range[2]) : stat.size - 1)
  if (start > end || start >= stat.size) {
    response.writeHead(416, { 'content-range': `bytes */${stat.size}` })
    response.end()
    return
  }
  response.writeHead(206, {
    ...baseHeaders,
    'content-length': end - start + 1,
    'content-range': `bytes ${start}-${end}/${stat.size}`,
  })
  if (request.method === 'HEAD') response.end()
  else createReadStream(filename, { start, end }).on('error', () => response.destroy()).pipe(response)
}

function listen(server, host, port) {
  return new Promise((resolve, reject) => {
    const onError = error => { server.off('listening', onListening); reject(error) }
    const onListening = () => { server.off('error', onError); resolve(server.address().port) }
    server.once('error', onError)
    server.once('listening', onListening)
    server.listen({ host, port })
  })
}

function closeServer(server) {
  return new Promise(resolve => {
    if (!server.listening) { resolve(); return }
    server.close(() => resolve())
  })
}

function publicOrigin(host, port) {
  return `http://${host}:${port}`
}

function outputName(kind, extension) {
  const id = randomUUID()
  return kind === 'scene' ? `review-${id}.maestro-scene.json` : `review-${id}_3d_scene.${extension}`
}

/**
 * Serves a prebuilt UI behind a deliberately tiny, provider-free
 * HTTP sandbox. The returned server owns only the fresh output directory and
 * an in-memory output index; nothing is recovered after a process restart.
 */
export async function startReviewServer({ uiDist, outputDir, host = LOOPBACK_HOST, port = 0, limits }) {
  const listenHost = validateListenHost(host)
  const requestedPort = parsePort(port)
  const exportsDir = path.join(outputDir, 'exports')
  const inputsDir = path.join(outputDir, 'inputs')
  const previewsDir = path.join(outputDir, 'previews')
  await fs.mkdir(exportsDir, { recursive: true })
  await fs.mkdir(inputsDir, { recursive: true })
  await fs.mkdir(previewsDir, { recursive: true })

  const uiFiles = await indexStaticUi(uiDist)
  const outputs = []
  const files = new Map()
  const inputs = new Map()
  const metadata = new Map()
  const blocked = []
  const previewFiles = new Set()
  const pendingInputs = new Set()
  let closed = false
  let writing = false
  let inputBytes = 0
  const budget = createWriteBudget(limits)

  const remember = ({ name, type, size, params, filename }) => {
    if (files.has(name)) throw new Error(`Review file name is already indexed: ${name}`)
    const item = {
      name,
      type,
      mode: type === 'video' ? '3d-scene-compositor' : type,
      size,
      created_at: Date.now() / 1000,
      favorite: false,
      url: `/api/v1/file/${encodeURIComponent(name)}?workspace=default`,
    }
    outputs.unshift(item)
    files.set(name, filename)
    metadata.set(name, { params })
    return item
  }

  const allowedOrigins = new Set()
  const allowedHosts = new Set()
  const isIndexedSource = source => {
    try {
      const url = new URL(source, 'http://review.invalid')
      // Relative references work from both the loopback editor and LAN preview
      // without violating the browser's same-origin CSP or render interceptor.
      if (!source.startsWith('/') || source.startsWith('//')) return false
      const file = url.pathname.match(/^\/api\/v1\/file\/([^/]+)$/)
      if (file) return files.has(decodeURIComponent(file[1]))
      const preview = url.pathname.match(PREVIEW_PATH)
      return Boolean(preview && previewFiles.has(`${preview[1]}.${preview[2]}`))
    } catch { return false }
  }
  const addAllowedOrigins = actualPort => {
    allowedOrigins.add(publicOrigin(LOOPBACK_HOST, actualPort))
    allowedOrigins.add(publicOrigin('localhost', actualPort))
    if (listenHost !== LOOPBACK_HOST) allowedOrigins.add(publicOrigin(listenHost, actualPort))
    allowedHosts.add(`${LOOPBACK_HOST}:${actualPort}`)
    allowedHosts.add(`localhost:${actualPort}`)
    if (listenHost !== LOOPBACK_HOST) allowedHosts.add(`${listenHost}:${actualPort}`)
  }

  const hostAllowed = request => {
    const host = request.headers.host
    return typeof host === 'string' && allowedHosts.has(host.toLowerCase())
  }

  const rejectForeignHost = (request, response) => {
    if (hostAllowed(request)) return false
    json(response, { detail: 'Review sandbox rejects an untrusted Host header.' }, 403)
    return true
  }

  const originAllowed = request => {
    const origin = request.headers.origin
    return !origin || allowedOrigins.has(origin)
  }

  const rejectForeignOrigin = (request, response) => {
    if (originAllowed(request)) return false
    json(response, { detail: 'Review sandbox rejects cross-origin writes.' }, 403)
    return true
  }

  const handler = async (request, response) => {
    let ownsWrite = false
    try {
      for (const [name, value] of Object.entries(REVIEW_HEADERS)) response.setHeader(name, value)
      const url = new URL(request.url || '/', 'http://127.0.0.1')
      const pathname = url.pathname
      if (rejectForeignHost(request, response)) return
      if (request.method !== 'GET' && request.method !== 'HEAD' && rejectForeignOrigin(request, response)) return
      if (request.method === 'POST') {
        if (request.socket.localAddress !== LOOPBACK_HOST) { json(response, { detail: 'LAN review is read-only; save from the loopback editor.' }, 403); return }
        if (writing || closed) { json(response, { detail: 'Review write in progress; retry after it finishes.' }, 409); return }
        writing = true
        ownsWrite = true
        if (Number(request.headers['content-length']) > MAX_REQUEST_BYTES) throw new RequestTooLargeError('Review sandbox request exceeds the 40 MB limit.')
      }

      if (request.method === 'GET' && pathname === '/api/v1/scene-template-review/status') {
        json(response, {
          sandbox: true,
          providers: 'blocked',
          real_apps: 'untouched',
          storage: 'temporary; no restart recovery',
          writeScope: 'loopback-only',
          quota: budget.snapshot(),
          outputCount: outputs.length,
          inputCount: inputs.size,
          inputBytes,
          blocked: [...blocked],
        })
        return
      }
      if (request.method === 'GET' && pathname === '/api/v1/outputs') {
        const type = url.searchParams.get('media_type')
        const listed = type ? outputs.filter(item => item.type === type) : outputs
        json(response, { outputs: listed, total: listed.length })
        return
      }
      if (request.method === 'GET' && pathname === '/api/v1/character-kits/library') {
        json(response, { version: 1, revision: 0, activeId: '', kits: {} })
        return
      }
      const metadataMatch = pathname.match(/^\/api\/v1\/outputs\/([^/]+)\/metadata$/)
      if (request.method === 'GET' && metadataMatch) {
        const name = decodeURIComponent(metadataMatch[1])
        json(response, metadata.get(name) || {}, metadata.has(name) ? 200 : 404)
        return
      }
      const fileMatch = pathname.match(/^\/api\/v1\/file\/([^/]+)$/)
      if ((request.method === 'GET' || request.method === 'HEAD') && fileMatch) {
        const name = decodeURIComponent(fileMatch[1])
        const filename = files.get(name)
        if (!filename) { json(response, { detail: 'Unknown review output.' }, 404); return }
        await sendFile(request, response, filename)
        return
      }
      const previewMatch = pathname.match(PREVIEW_PATH)
      if ((request.method === 'GET' || request.method === 'HEAD') && previewMatch) {
        const name = path.basename(previewMatch[1] + '.' + previewMatch[2])
        if (!previewFiles.has(name)) { json(response, { detail: 'Preview is not available.' }, 404); return }
        await sendFile(request, response, path.join(previewsDir, name))
        return
      }
      if (request.method === 'POST' && pathname === '/api/v1/scenes') {
        const payload = JSON.parse((await readBody(request)).toString('utf8'))
        validateReviewSnapshot(payload.scene, isIndexedSource)
        if (payload.preview && !/^data:image\//i.test(payload.preview)) throw new Error('Preview must be an inline image.')
        const name = outputName('scene', 'json')
        const filename = path.join(exportsDir, name)
        const bytes = Buffer.from(JSON.stringify(payload.scene, null, 2))
        budget.reserve(bytes.length + Buffer.byteLength(JSON.stringify(payload)))
        await fs.writeFile(filename, bytes, { flag: 'wx' })
        const saved = remember({ name, type: 'scene', size: bytes.length, params: { scene: payload.scene, preview: payload.preview }, filename })
        json(response, { ...saved, thumbnail_url: payload.preview || null })
        return
      }
      if (request.method === 'POST' && pathname === '/api/v1/scenes/recordings') {
        const raw = await readBody(request)
        const formRequest = new Request('http://review-sandbox.local/', {
          method: 'POST',
          headers: { 'content-type': request.headers['content-type'] || '' },
          body: raw,
        })
        const form = await formRequest.formData()
        const video = form.get('file')
        const params = JSON.parse(String(form.get('metadata') || '{}'))
        if (!video || typeof video.arrayBuffer !== 'function') throw new Error('Expected recording and editable scene snapshot.')
        validateReviewSnapshot(params.scene, isIndexedSource)
        const bytes = Buffer.from(await video.arrayBuffer())
        if (bytes.subarray(4, 8).toString('ascii') !== 'ftyp') throw new Error('Expected MP4 recording; no silent fake conversion is accepted.')
        const name = outputName('video', 'mp4')
        const filename = path.join(exportsDir, name)
        const sidecar = JSON.stringify({ params }, null, 2)
        budget.reserve(bytes.length + Buffer.byteLength(sidecar))
        await fs.writeFile(filename, bytes, { flag: 'wx' })
        await fs.writeFile(path.join(exportsDir, `${name}.metadata.json`), sidecar, { flag: 'wx' })
        console.log(`RECORDED template=${params.scene.narrative?.templateId || 'unknown'} name=${name} bytes=${bytes.length}`)
        json(response, remember({ name, type: 'video', size: bytes.length, params, filename }))
        return
      }
      if (pathname.startsWith('/api/') || pathname.startsWith('/classic')) {
        if (blocked.length >= MAX_BLOCKED_REQUESTS) blocked.shift()
        blocked.push(`${request.method} ${pathname}`)
        json(response, { detail: 'Isolated review sandbox: generators, model downloads and other application APIs are disabled.' }, 403)
        return
      }
      const uiFile = uiFiles.get(pathname === '/' || pathname === '/scene-template-review' ? '/index.html' : pathname)
      if (uiFile && (request.method === 'GET' || request.method === 'HEAD')) {
        await sendFile(request, response, uiFile)
        return
      }
      json(response, { detail: 'Not found.' }, 404)
    } catch (error) {
      const message = error?.code ? 'Review file operation failed.' : error instanceof Error ? error.message : String(error)
      const status = error instanceof RequestTooLargeError ? 413 : error?.code === 'ENOENT' ? 404 : 400
      json(response, { detail: message }, status)
    } finally {
      if (ownsWrite) writing = false
    }
  }

  const makeHttpServer = () => {
    const server = http.createServer((request, response) => { void handler(request, response) })
    server.requestTimeout = 30_000
    server.headersTimeout = 10_000
    server.maxHeadersCount = 64
    return server
  }
  const servers = [makeHttpServer()]
  let actualPort
  try {
    actualPort = await listen(servers[0], LOOPBACK_HOST, requestedPort)
    addAllowedOrigins(actualPort)
    if (listenHost !== LOOPBACK_HOST) {
      const lanServer = makeHttpServer()
      servers.push(lanServer)
      await listen(lanServer, listenHost, actualPort)
    }
  } catch (error) {
    await Promise.all(servers.map(closeServer))
    throw error
  }

  const close = async () => {
    if (closed) return
    closed = true
    await Promise.all(servers.map(closeServer))
  }
  const registerPreview = name => {
    if (!PREVIEW_PATH.test(`/scene-template-previews/${name}`)) throw new Error(`Unsafe preview name “${name}”.`)
    previewFiles.add(name)
  }
  const registerInput = async name => {
    const safeName = validateInputName(name)
    if (files.has(safeName) || pendingInputs.has(safeName)) throw new Error(`Review input name is already indexed: ${safeName}`)
    if (inputs.size >= MAX_INPUTS) throw new Error(`Review input limit exceeded (${MAX_INPUTS} files).`)
    pendingInputs.add(safeName)
    try {
      const filename = path.join(inputsDir, safeName)
      let stat
      try {
        stat = await fs.lstat(filename)
      } catch (error) {
        if (error?.code === 'ENOENT') throw new Error(`Review input is missing: ${safeName}`)
        throw error
      }
      if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Review input must be a regular non-symlink file: ${safeName}`)
      if (stat.size === 0) throw new Error(`Review input must not be empty: ${safeName}`)
      const fileLimit = MEDIA_INPUT.test(safeName) ? MAX_MEDIA_INPUT_FILE_BYTES : MAX_INPUT_FILE_BYTES
      if (stat.size > fileLimit) throw new Error(`Review input exceeds the ${fileLimit} byte file limit: ${safeName}`)

      // A registered input is resolved from this fresh directory only. The
      // realpath check also rejects a path that was swapped for a link between
      // the lstat above and indexing.
      const rootStat = await fs.lstat(inputsDir)
      if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
        throw new Error(`Review input directory must not be a symlink: ${safeName}`)
      }
      // Resolve legitimate platform aliases in ancestors (e.g. macOS /var),
      // while forbidding replacement of the actual input directory itself.
      const inputRoot = await fs.realpath(inputsDir)
      const realFilename = await fs.realpath(filename)
      const relative = path.relative(inputRoot, realFilename)
      if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
        throw new Error(`Review input is outside the input directory: ${safeName}`)
      }

      // Keep the final checks immediately adjacent to the synchronous Map/set
      // operations. There is no await between this check and commit, so
      // concurrent registrations cannot overwrite one another or exceed the
      // finite input budget.
      if (files.has(safeName)) throw new Error(`Review input name is already indexed: ${safeName}`)
      if (inputs.size >= MAX_INPUTS) throw new Error(`Review input limit exceeded (${MAX_INPUTS} files).`)
      if (inputBytes + stat.size > MAX_INPUT_BYTES) throw new Error(`Review input byte limit exceeded (${MAX_INPUT_BYTES} bytes).`)

      const item = {
        name: safeName,
        size: stat.size,
        url: `/api/v1/file/${encodeURIComponent(safeName)}?workspace=default`,
      }
      inputs.set(safeName, { ...item, filename })
      files.set(safeName, filename)
      inputBytes += stat.size
      return item
    } finally {
      pendingInputs.delete(safeName)
    }
  }
  const localOrigin = publicOrigin(LOOPBACK_HOST, actualPort)
  return {
    close,
    outputDir,
    exportsDir,
    inputsDir,
    previewsDir,
    localOrigin,
    lanOrigin: listenHost === LOOPBACK_HOST ? null : publicOrigin(listenHost, actualPort),
    port: actualPort,
    blocked,
    registerPreview,
    registerInput,
    snapshot: () => ({ outputs: outputs.map(item => ({ ...item })), blocked: [...blocked] }),
  }
}

export {
  MAX_BLOCKED_REQUESTS,
  MAX_INPUTS,
  MAX_INPUT_FILE_BYTES,
  MAX_MEDIA_INPUT_FILE_BYTES,
  MAX_INPUT_BYTES,
  MAX_REQUEST_BYTES,
  LOOPBACK_HOST,
}
