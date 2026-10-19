import { createHash, randomUUID } from 'node:crypto'
import { constants, createReadStream } from 'node:fs'
import fs from 'node:fs/promises'
import path from 'node:path'
import { TextDecoder } from 'node:util'
import { parseShowcaseManifest } from '../../src/features/sceneTemplates/showcaseManifest.ts'
import { builtInGraphicSources } from '../../src/features/sceneTemplates/sceneBuilders.ts'

export const MAX_SHOWCASE_BYTES = 512 * 1024 * 1024
export const MAX_SHOWCASE_REFERENCES = 256
export const MAX_SHOWCASE_MANIFEST_BYTES = 1 * 1024 * 1024
export const MAX_SHOWCASE_INPUTS = 64
export const MAX_SHOWCASE_INPUT_FILE_BYTES = 4 * 1024 * 1024
export const MAX_SHOWCASE_INPUT_BYTES = 128 * 1024 * 1024

const SAFE_BASENAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$/
const SAFE_INPUT_BASENAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.(?:jpe?g|png|webp)$/i
const SHOWCASE_URL_PREFIX = '/scene-showcase/'
const SHOWCASE_EXTENSIONS = new Set(['mp4', 'png', 'jpg', 'json'])
const decoder = new TextDecoder('utf-8', { fatal: true })

// The deterministic SVG overlays emitted by sceneBuilders.effect(), taken from the builders themselves so a new
// one (the broadside bolt) is accepted without a second copy. They stay inline because they are compositor
// primitives, not user-provided raster inputs; any other SVG/data URL stays rejected (exact match).
const SHOWCASE_GRAPHIC_SOURCES = new Set(builtInGraphicSources())

const SHOWCASE_ATMOSPHERE_KINDS = new Set([
  'rain', 'snow', 'dust', 'embers', 'fog', 'smoke', 'ash', 'fireflies',
  'confetti', 'bokeh', 'sparkles', 'bubbles', 'speedlines', 'leaves',
])

/** Return true only for a graphic emitted byte-for-byte by sceneBuilders.effect. */
export function isBuiltInShowcaseGraphic(source) {
  return typeof source === 'string' && SHOWCASE_GRAPHIC_SOURCES.has(source)
}

function isBuiltInShowcaseEffect(layer) {
  const kind = layer?.atmosphere?.kind
  if (!SHOWCASE_ATMOSPHERE_KINDS.has(kind)) return false
  return layer.source === undefined || layer.source === '' || layer.source === `maestro-effect:${kind}`
}

function fail(message) {
  throw new Error(`Showcase package: ${message}`)
}

function isNotFound(error) {
  return error?.code === 'ENOENT'
}

async function assertDirectory(directory, label) {
  let info
  try {
    info = await fs.lstat(directory)
  } catch (error) {
    if (isNotFound(error)) fail(`${label} does not exist.`)
    throw error
  }
  if (!info.isDirectory() || info.isSymbolicLink()) fail(`${label} must be a regular, non-symlink directory.`)
  return directory
}

async function assertAbsent(filename, label) {
  try {
    await fs.lstat(filename)
  } catch (error) {
    if (isNotFound(error)) return
    throw error
  }
  fail(`${label} already exists; refusing to overwrite it.`)
}

async function packageRoot(directory) {
  if (typeof directory !== 'string' || !directory.trim()) fail('showcaseDir is required.')
  const absolute = path.resolve(directory)
  await assertDirectory(absolute, 'showcaseDir')
  return { absolute, real: await fs.realpath(absolute) }
}

function within(root, filename) {
  const relative = path.relative(root, filename)
  return relative && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)
}

async function regularPackageFile(filename, root, label) {
  let info
  try {
    info = await fs.lstat(filename)
  } catch (error) {
    if (isNotFound(error)) fail(`${label} is missing.`)
    throw error
  }
  if (!info.isFile() || info.isSymbolicLink()) fail(`${label} must be a regular, non-symlink file.`)
  const real = await fs.realpath(filename)
  if (!within(root, real)) fail(`${label} resolves outside showcaseDir.`)
  return { filename, size: info.size }
}

function referenceBasename(reference, label) {
  if (typeof reference?.url !== 'string' || !reference.url.startsWith(SHOWCASE_URL_PREFIX)) fail(`${label}.url must be a relative /scene-showcase/ URL.`)
  const name = reference.url.slice(SHOWCASE_URL_PREFIX.length)
  if (!SAFE_BASENAME.test(name) || path.basename(name) !== name) fail(`${label}.url contains an unsafe basename.`)
  const extension = path.extname(name).slice(1).toLowerCase()
  if (!SHOWCASE_EXTENSIONS.has(extension)) fail(`${label}.url has an unsupported extension.`)
  if (reference.url !== `${SHOWCASE_URL_PREFIX}${name}`) fail(`${label}.url must not contain a query, fragment or alternate path.`)
  return { name, extension }
}

/** Return every manifest reference, including repeated references. */
export function collectShowcaseReferences(manifest) {
  const references = []
  const add = reference => { if (reference) references.push(reference) }
  for (const item of manifest.items) {
    add(item.video)
    add(item.poster)
    add(item.scene)
    for (const shot of item.shots || []) add(shot.scene)
  }
  return references
}

async function readManifest(root) {
  const filename = path.join(root, 'manifest.json')
  const file = await regularPackageFile(filename, root, 'manifest.json')
  if (!Number.isSafeInteger(file.size) || file.size <= 0 || file.size > MAX_SHOWCASE_MANIFEST_BYTES) {
    fail(`manifest.json must be between 1 and ${MAX_SHOWCASE_MANIFEST_BYTES} bytes.`)
  }
  const bytes = await fs.readFile(filename)
  if (bytes.length > MAX_SHOWCASE_MANIFEST_BYTES) fail('manifest.json exceeds the 1 MiB limit.')
  let parsed
  try {
    parsed = JSON.parse(decoder.decode(bytes))
  } catch (error) {
    fail(`manifest.json is not valid UTF-8 JSON: ${error instanceof Error ? error.message : String(error)}`)
  }
  let manifest
  try {
    manifest = parseShowcaseManifest(parsed)
  } catch (error) {
    fail(error instanceof Error ? error.message : String(error))
  }
  const normalized = Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`)
  if (normalized.length > MAX_SHOWCASE_MANIFEST_BYTES) fail('the validated manifest exceeds the 1 MiB limit.')
  return { filename, manifest, normalized }
}

async function sha256File(filename) {
  const hash = createHash('sha256')
  const stream = createReadStream(filename)
  for await (const chunk of stream) hash.update(chunk)
  return hash.digest('hex')
}

function sha256Bytes(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

const SAFE_WORKSPACE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/

function indexedInputName(source, availableInputs, label) {
  if (typeof source !== 'string' || source.includes('\\') || !source.startsWith('/') || source.startsWith('//')) {
    fail(`${label} must use a local indexed input URL; external, data and disk sources are not allowed.`)
  }
  let url
  try {
    url = new URL(source, 'http://showcase.invalid')
  } catch {
    fail(`${label} has an invalid indexed input URL.`)
  }
  if (url.origin !== 'http://showcase.invalid') fail(`${label} must be a relative indexed input URL.`)
  const encodedName = url.pathname.match(/^\/api\/v1\/file\/([^/]+)$/)?.[1]
  if (!encodedName) fail(`${label} must use /api/v1/file/<basename>.`)
  let name
  try {
    name = decodeURIComponent(encodedName)
  } catch {
    fail(`${label} has an invalid encoded input basename.`)
  }
  if (!SAFE_INPUT_BASENAME.test(name) || path.basename(name) !== name) fail(`${label} has an unsafe indexed input basename.`)
  if (url.hash || [...url.searchParams.keys()].some(key => key !== 'workspace') || new Set(url.searchParams.keys()).size !== url.searchParams.size) {
    fail(`${label} may only contain one optional workspace query parameter.`)
  }
  const workspace = url.searchParams.get('workspace')
  if (workspace !== null && !SAFE_WORKSPACE.test(workspace)) fail(`${label} has an unsafe workspace query parameter.`)
  if (!availableInputs.has(name)) fail(`${label} references input ${name}, which is not present in the verified inputs/.`)
  return name
}

function sceneSnapshotFromBytes(bytes, reference, label, availableInputs) {
  let parsed
  try {
    const text = decoder.decode(bytes).replace(/^\uFEFF/, '')
    parsed = JSON.parse(text)
  } catch (error) {
    fail(`${label} is not valid UTF-8 scene JSON: ${error instanceof Error ? error.message : String(error)}`)
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) fail(`${label} must contain a scene object.`)
  if (parsed.generationPolicy !== 'provided_only') fail(`${label} must declare generationPolicy provided_only.`)
  if (parsed.name !== reference.sceneName) fail(`${label} name does not match sceneName “${reference.sceneName}”.`)
  if (parsed.audioTracks !== undefined && (!Array.isArray(parsed.audioTracks) || parsed.audioTracks.length > 0)) fail(`${label} must be silent; audioTracks are not allowed in this package.`)
  if (!Array.isArray(parsed.layers)) fail(`${label} must contain a layers array.`)
  for (let index = 0; index < parsed.layers.length; index += 1) {
    const layer = parsed.layers[index]
    const layerLabel = `${label} layer ${index + 1}`
    if (!layer || typeof layer !== 'object' || Array.isArray(layer)) fail(`${layerLabel} is not an object.`)
    if (layer.thumbnail !== undefined && layer.thumbnail !== '') indexedInputName(layer.thumbnail, availableInputs, `${layerLabel} thumbnail`)
    if (layer.type === 'image') {
      if (isBuiltInShowcaseGraphic(layer.source)) continue
      indexedInputName(layer.source, availableInputs, `${layerLabel} source`)
      continue
    }
    if (layer.type === 'effect') {
      if (!isBuiltInShowcaseEffect(layer)) fail(`${layerLabel} has an unknown atmosphere or mismatched maestro-effect source.`)
      continue
    }
    if (layer.type === 'camera') {
      if (layer.source !== undefined && layer.source !== '') fail(`${layerLabel} has an external source; procedural/effect/camera layers must be local.`)
      continue
    }
    fail(`${layerLabel} type ${String(layer.type)} is not allowed; model3d, video, GLB and overlay sources are rejected.`)
  }
  if (parsed.narrative?.assets !== undefined) {
    if (!Array.isArray(parsed.narrative.assets)) fail(`${label} narrative assets must be an array.`)
    for (let index = 0; index < parsed.narrative.assets.length; index += 1) {
      const asset = parsed.narrative.assets[index]
      const assetLabel = `${label} narrative asset ${index + 1}`
      if (!asset || typeof asset !== 'object' || Array.isArray(asset) || asset.type !== 'image') {
        fail(`${assetLabel} must be a raster input; model3d/GLB/video assets are rejected.`)
      }
      indexedInputName(asset.source, availableInputs, `${assetLabel} source`)
    }
  }
  return parsed
}

async function verifyReference(reference, root, label, availableInputs) {
  const { name, extension } = referenceBasename(reference, label)
  if (name === 'manifest.json') fail(`${label}.url cannot reuse the package manifest name.`)
  const source = path.join(root, name)
  const file = await regularPackageFile(source, root, `${label} (${name})`)
  if (!Number.isSafeInteger(file.size) || file.size <= 0) fail(`${label} must not be empty.`)
  if (file.size !== reference.bytes) fail(`${label} declares ${reference.bytes} bytes but the file has ${file.size}.`)
  if (extension === 'json' && file.size > 4 * 1024 * 1024) fail(`${label} exceeds the 4 MiB scene JSON limit.`)

  let actualHash
  if (extension === 'json') {
    const bytes = await fs.readFile(source)
    actualHash = sha256Bytes(bytes)
    if (actualHash !== reference.sha256) fail(`${label} SHA-256 does not match the manifest.`)
    sceneSnapshotFromBytes(bytes, reference, label, availableInputs)
  } else {
    actualHash = await sha256File(source)
    if (actualHash !== reference.sha256) fail(`${label} SHA-256 does not match the manifest.`)
  }
  return { ...reference, name, extension, source, size: file.size, sha256: actualHash }
}

function validateInputBasename(name) {
  if (!SAFE_INPUT_BASENAME.test(name) || path.basename(name) !== name || name.includes('/') || name.includes('\\')) {
    fail(`input ${JSON.stringify(name)} must be a safe JPG, JPEG, PNG or WebP basename.`)
  }
  return name
}

async function inputDirectory(root) {
  const directory = path.join(root, 'inputs')
  let info
  try {
    info = await fs.lstat(directory)
  } catch (error) {
    if (isNotFound(error)) return null
    throw error
  }
  if (!info.isDirectory() || info.isSymbolicLink()) fail('inputs must be a regular, non-symlink directory.')
  return { absolute: directory, real: await fs.realpath(directory) }
}

async function collectInputNames(directory) {
  const handle = await fs.opendir(directory)
  const names = []
  try {
    for await (const entry of handle) {
      if (names.length >= MAX_SHOWCASE_INPUTS) fail(`inputs contains more than ${MAX_SHOWCASE_INPUTS} files.`)
      if (entry.isDirectory() || entry.isSymbolicLink() || !entry.isFile()) fail(`inputs/${entry.name} must be a regular file, not a directory or symlink.`)
      names.push(entry.name)
    }
  } finally {
    await handle.close().catch(() => undefined)
  }
  return names.sort()
}

async function verifyInputs(root) {
  const directory = await inputDirectory(root)
  if (!directory) return []
  const names = await collectInputNames(directory.absolute)
  let total = 0
  const records = []
  for (const name of names) {
    validateInputBasename(name)
    const source = path.join(directory.real, name)
    const file = await regularPackageFile(source, directory.real, `inputs/${name}`)
    if (!Number.isSafeInteger(file.size) || file.size <= 0) fail(`inputs/${name} must not be empty.`)
    if (file.size > MAX_SHOWCASE_INPUT_FILE_BYTES) fail(`inputs/${name} exceeds the 4 MiB input limit.`)
    total += file.size
    if (total > MAX_SHOWCASE_INPUT_BYTES) fail(`inputs exceed the ${MAX_SHOWCASE_INPUT_BYTES} byte total limit.`)
    records.push({ name, source, size: file.size, sha256: await sha256File(source) })
  }
  return records
}

async function copyAndVerify(record, target) {
  await fs.copyFile(record.source, target, constants.COPYFILE_EXCL)
  const info = await fs.lstat(target)
  if (!info.isFile() || info.isSymbolicLink()) fail(`copied ${record.name} is not a regular file.`)
  if (info.size !== record.size) fail(`copied ${record.name} changed size.`)
  const actualHash = await sha256File(target)
  if (actualHash !== record.sha256) fail(`copied ${record.name} failed SHA-256 verification.`)
}

async function stageShowcaseFiles(records, normalized, uiDist) {
  const finalDirectory = path.join(uiDist, 'scene-showcase')
  await assertAbsent(finalDirectory, 'uiDist/scene-showcase')
  const staging = path.join(uiDist, `.scene-showcase-stage-${randomUUID()}`)
  await fs.mkdir(staging)
  try {
    for (const record of records) await copyAndVerify(record, path.join(staging, record.name))
    await fs.writeFile(path.join(staging, 'manifest.json'), normalized, { flag: 'wx' })
    await fs.rename(staging, finalDirectory)
  } catch (error) {
    await fs.rm(staging, { recursive: true, force: true }).catch(() => undefined)
    throw error
  }
  return finalDirectory
}

async function stageInputFiles(records, outputDir) {
  if (records.length === 0) return null
  const finalDirectory = path.join(outputDir, 'inputs')
  await assertAbsent(finalDirectory, 'outputDir/inputs')
  const staging = path.join(outputDir, `.showcase-inputs-stage-${randomUUID()}`)
  await fs.mkdir(staging)
  try {
    for (const record of records) await copyAndVerify(record, path.join(staging, record.name))
    await fs.rename(staging, finalDirectory)
  } catch (error) {
    await fs.rm(staging, { recursive: true, force: true }).catch(() => undefined)
    throw error
  }
  return finalDirectory
}

/**
 * Validate a showcase package and stage its verified snapshots before the HTTP
 * server indexes its UI. No network or application API is used here.
 */
export async function prepareShowcase({ showcaseDir, uiDist, outputDir } = {}) {
  if (typeof uiDist !== 'string' || !uiDist.trim()) fail('uiDist is required.')
  if (typeof outputDir !== 'string' || !outputDir.trim()) fail('outputDir is required.')
  await assertDirectory(path.resolve(uiDist), 'uiDist')
  await assertDirectory(path.resolve(outputDir), 'outputDir')
  const root = await packageRoot(showcaseDir)
  const { manifest, normalized } = await readManifest(root.real)
  const allReferences = collectShowcaseReferences(manifest)
  if (allReferences.length > MAX_SHOWCASE_REFERENCES) fail(`manifest references more than ${MAX_SHOWCASE_REFERENCES} files.`)

  const unique = new Map()
  for (let index = 0; index < allReferences.length; index += 1) {
    const reference = allReferences[index]
    const label = `manifest reference ${index + 1}`
    const { name } = referenceBasename(reference, label)
    const previous = unique.get(name)
    if (previous && (previous.sha256 !== reference.sha256 || previous.bytes !== reference.bytes || previous.sceneName !== reference.sceneName)) {
      fail(`${label} conflicts with another reference to ${name}.`)
    }
    if (!previous) unique.set(name, reference)
  }
  const expectedBytes = [...unique.values()].reduce((total, reference) => total + reference.bytes, 0)
  if (expectedBytes > MAX_SHOWCASE_BYTES) fail(`referenced files exceed the ${MAX_SHOWCASE_BYTES} byte total limit.`)

  const inputRecords = await verifyInputs(root.real)
  const availableInputs = new Set(inputRecords.map(record => record.name))
  let actualBytes = 0
  const records = []
  let index = 0
  for (const reference of unique.values()) {
    index += 1
    const record = await verifyReference(reference, root.real, `manifest reference ${index}`, availableInputs)
    actualBytes += record.size
    if (actualBytes > MAX_SHOWCASE_BYTES) fail(`referenced files exceed the ${MAX_SHOWCASE_BYTES} byte total limit.`)
    records.push(record)
  }
  let showcaseDirectory
  let inputDirectoryPath
  try {
    showcaseDirectory = await stageShowcaseFiles(records, normalized, path.resolve(uiDist))
    inputDirectoryPath = await stageInputFiles(inputRecords, path.resolve(outputDir))
  } catch (error) {
    if (showcaseDirectory) await fs.rm(showcaseDirectory, { recursive: true, force: true }).catch(() => undefined)
    if (inputDirectoryPath) await fs.rm(inputDirectoryPath, { recursive: true, force: true }).catch(() => undefined)
    throw error
  }

  return {
    showcaseDir: root.absolute,
    manifest,
    manifestPath: path.join(showcaseDirectory, 'manifest.json'),
    uiShowcaseDir: showcaseDirectory,
    references: records,
    allReferences,
    referenceCount: allReferences.length,
    bytes: actualBytes,
    inputDirectory: inputDirectoryPath,
    inputs: inputRecords,
    inputNames: inputRecords.map(record => record.name),
  }
}

/** Register staged canonical inputs only after startReviewServer has started. */
export async function registerShowcaseInputs(server, preparation) {
  const target = server && typeof server.server?.registerInput === 'function' ? server.server : server
  const names = Array.isArray(preparation) ? preparation : preparation?.inputNames
  if (!target || typeof target.registerInput !== 'function') fail('registerShowcaseInputs needs a started review server.')
  if (!Array.isArray(names)) fail('registerShowcaseInputs needs prepared input names.')
  const seen = new Set()
  const registered = []
  for (const name of names) {
    validateInputBasename(name)
    if (seen.has(name)) fail(`input ${name} is listed more than once.`)
    seen.add(name)
    registered.push(await target.registerInput(name))
  }
  return registered
}

export const prepareShowcasePackage = prepareShowcase
export const registerPreparedShowcaseInputs = registerShowcaseInputs
