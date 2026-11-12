// CPU proof of a metric box room. Prints one JSON line. `--sheet <ppm>` also writes the frame.
// The pixel oracle lives in tests/test_room_box.py (numpy), not in this painter.
import { writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { stageRoomBox } from '../src/features/scene3d/roomBox.ts'
import { renderRoomBoxFrame } from '../src/features/scene3d/roomBoxRaster.ts'

const ADULT = [40, 110, 190]
const NEAR = [190, 60, 70]
const DOOR = [176, 78, 36]

export function proofDocument() {
  const document = createDefaultScene3DDocument()
  return stageRoomBox(document, {
    size: { w: 4, d: 5, h: 2.6 },
    door: { wall: 'back', x: 0, w: 0.9, h: 2 },
    characters: [
      { x: 1.2, z: 2.48, heightM: 1.75, color: ADULT },
      { x: -1, z: -1.6, heightM: 1.75, color: NEAR },
    ],
  })
}

function same(frame, x, y, rgb) {
  const i = (y * frame.width + x) * 4
  return frame.pixels[i] === rgb[0] && frame.pixels[i + 1] === rgb[1] && frame.pixels[i + 2] === rgb[2]
}

function span(frame, rgb) {
  let minX = frame.width, maxX = -1, minY = frame.height, maxY = -1, count = 0
  for (let y = 0; y < frame.height; y += 1) {
    for (let x = 0; x < frame.width; x += 1) {
      if (!same(frame, x, y, rgb)) continue
      count += 1
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
  }
  return { count, minX, maxX, minY, maxY, height: maxY - minY + 1, centerX: Math.round((minX + maxX) / 2) }
}

export function measureProof(width = 960) {
  const document = proofDocument()
  const frame = renderRoomBoxFrame(document, width)
  const adult = span(frame, ADULT)
  const near = span(frame, NEAR)
  const door = span(frame, DOOR)
  const underY = Math.min(frame.height - 1, adult.maxY + 1)
  const under = (adult.maxY + 1) * frame.width + adult.centerX
  const i = under * 4
  return {
    width: frame.width,
    height: frame.height,
    eye: document.camera.eye,
    look: document.camera.look,
    fov: document.camera.fov,
    adult,
    near,
    door,
    below: [frame.pixels[i], frame.pixels[i + 1], frame.pixels[i + 2]],
    belowY: underY,
    point: [1.2, 0, 2.48],
    frame,
  }
}

function writePpm(frame, path) {
  const header = `P6\n${frame.width} ${frame.height}\n255\n`
  const body = Buffer.alloc(frame.width * frame.height * 3)
  for (let p = 0, q = 0; p < frame.pixels.length; p += 4, q += 3) {
    body[q] = frame.pixels[p]
    body[q + 1] = frame.pixels[p + 1]
    body[q + 2] = frame.pixels[p + 2]
  }
  writeFileSync(path, Buffer.concat([Buffer.from(header), body]))
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href
if (isMain) {
  const measured = measureProof()
  const sheet = process.argv.indexOf('--sheet')
  if (sheet >= 0 && process.argv[sheet + 1]) writePpm(measured.frame, process.argv[sheet + 1])
  const { frame, ...printed } = measured
  process.stdout.write(`${JSON.stringify(printed)}\n`)
}
