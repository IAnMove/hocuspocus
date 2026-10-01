// Compile one Video 3D template, or paint cheap software frames of a document.
import { readFileSync } from 'node:fs'
import { deflateSync } from 'node:zlib'
import { createHash } from 'node:crypto'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'

const command = process.argv[2]
if (command === 'document') write(compileDocument(process.argv[3]))
else if (command === 'preview') write(preview(JSON.parse(readFileSync(0, 'utf8'))))
else throw new Error('use document <id> or preview')

function compileDocument(id) {
  let document
  try { document = applyScene3DTemplate(id) }
  catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (message.startsWith('unknown_template:')) throw error
    throw new Error(`unknown_template:${id}`)
  }
  const parsed = parseScene3DDocument(document)
  if (!parsed || parsed.templateId !== id) throw new Error(`unknown_template:${id}`)
  return parsed
}

function preview(body) {
  const document = parseScene3DDocument(body.document)
  if (!document) throw new Error('invalid_world3d_document')
  const times = (body.times || [0, document.duration / 2, document.duration]).map(Number)
  return {
    templateId: document.templateId,
    frames: times.map(time => frame(document, time)),
    pending: document.slots.filter(slot => !slot.sourceUrl).map(slot => ({ id: slot.id, role: slot.slot, media: slot.media })),
    loadErrors: [],
  }
}

function frame(document, time) {
  const rendered = renderScene3DSoftware(document, time)
  const png = encodePng(rendered.width, rendered.height, rendered.pixels)
  return {
    time, width: rendered.width, height: rendered.height,
    sha256: createHash('sha256').update(png).digest('hex'),
    png: png.toString('base64'),
  }
}

function write(value) {
  process.stdout.write(JSON.stringify(value))
}

function encodePng(width, height, rgba) {
  const raw = Buffer.alloc((width * 4 + 1) * height)
  for (let y = 0; y < height; y += 1) {
    const start = y * width * 4
    raw.set(rgba.subarray(start, start + width * 4), y * (width * 4 + 1) + 1)
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8
  ihdr[9] = 6
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk('IHDR', ihdr),
    pngChunk('IDAT', deflateSync(raw)),
    pngChunk('IEND', Buffer.alloc(0)),
  ])
}

function pngChunk(type, data) {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length)
  const body = Buffer.concat([Buffer.from(type), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body) >>> 0)
  return Buffer.concat([length, body, crc])
}

function crc32(buffer) {
  let crc = -1
  for (const value of buffer) {
    crc ^= value
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0)
  }
  return crc ^ -1
}
