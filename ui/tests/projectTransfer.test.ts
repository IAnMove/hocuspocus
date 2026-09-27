import assert from 'node:assert/strict'
import test from 'node:test'
import JSZip from 'jszip'
import {
  PACKAGE_KIND, TEMPLATE_KIND, cinemaExtensionOf, classifyUrl, collectAssetUses,
  collectUnknownFields, documentIssues, isTemplateWrapper, uniqueAssetUses, sha256Hex,
  safeZipMember,
} from '../src/features/project-transfer/format.ts'
import { preflightBytes } from '../src/features/project-transfer/preflight.ts'
import { canImport, encodeReassign, pickerToReassign, repairAssets } from '../src/features/project-transfer/reassign.ts'

const glb = {
  workspaceId: 'film', filename: 'hero.glb', url: '/api/v1/file/hero.glb?workspace=film', assetId: 'asset_hero',
}
const voice = {
  workspaceId: 'film', filename: 'voice.wav', url: '/api/v1/file/voice.wav?workspace=film', assetId: 'asset_voice',
}
const screen = {
  workspaceId: 'film', filename: 'screen.png', url: '/api/v1/file/screen.png?workspace=film', assetId: 'asset_screen',
}

function shot(title: string) {
  return {
    version: 1, units: 'meters', up: 'y', width: 1280, height: 720, fps: 30, duration: 4, templateId: 'two-shot',
    camera: { family: 'establishment', eye: [0, 1.6, 4.2], look: [0, 1, 0], fov: 50 },
    light: { kind: 'directional', direction: [-0.35, -1, -0.25], intensity: 1.15, color: '#fff4e5' },
    environment: { reflectiveFloor: true, platform: true, bloom: 0.48 },
    texts: [{ id: 'title', text: title, start: 0, end: 3, preset: 'impact', x: 50, y: 80, size: 9, color: '#ffe3a0', rotation: 0 }],
    worldSfx: [{ id: 'portal-1', kind: 'portal', start: 0, end: 2, position: { x: 0, y: 1.1, z: -1.2 }, rotation: { x: 0, y: 0, z: 0 }, scale: 1.4, intensity: 1, color: '#88ccff', seed: 1, sound: true, volume: 0.25 }],
    sfx: [{ id: 'flash-1', kind: 'sparks', start: 0.2, end: 1.2, x: 50, y: 50, size: 65, intensity: 1, color: '#ffbb55', seed: 3, sound: true, volume: 0.25 }],
    slots: [{
      id: 'subject_1', slot: 'subject_1', position: [-0.85, 0, 0], rotationY: 0.35, scale: 1,
      sourceUrl: glb.url, sourceRef: glb, media: 'model3d', clip: { index: 0, name: 'Idle' },
      clipPlayback: { speed: 1, start: 0, loop: true }, motion: { to: [0.85, 0, 0], easing: 'smooth' },
      speech: { version: 1, enabled: true, cues: [{ start: 0, end: 0.4, viseme: 'A' }], driver: 'imported', start: 0, offset: 0, gain: 1, strength: 0.85, clean: true, style: 'soft', lip: '#874d47', expression: 'neutral', blink: true, eyes: true, audio: voice },
      screen: { sourceUrl: screen.url, sourceRef: screen, media: 'image', mode: 'mesh', targetMesh: 'SCREEN_CONTENT', anchor: '', offset: [0, 0, 0], pitch: 0, yaw: 0, roll: 0, width: 4, height: 3, style: 'monitor', fit: 'contain', start: 0, speed: 1, loop: true, flipY: false },
    }],
    soundtrack: [{ id: 'bed', audio: voice, start: 0, offset: 0, gain: 0.8 }],
  }
}

test('two shots sharing GLB and audio produce one unique media key each', () => {
  const uses = [...collectAssetUses(shot('One'), 'shot-1'), ...collectAssetUses(shot('Two'), 'shot-2')]
  const unique = uniqueAssetUses(uses)
  assert.equal(unique.filter(item => item.filename === 'hero.glb').length, 1)
  assert.equal(unique.filter(item => item.filename === 'voice.wav').length, 1)
  assert.ok(uses.some(item => item.role.includes('speech.audio')))
  assert.ok(uses.some(item => item.role.includes('screen')))
  const withPortal = {
    ...shot('Portal'),
    worldSfx: [
      { id: 'tv', kind: 'media_portal', start: 0, end: 3, sourceUrl: '/api/v1/uploads/portal.png' },
      { id: 'stock', kind: 'media_portal', start: 0, end: 3, sourceUrl: '/examples/tv-head-face.png' },
    ],
  }
  const portalUses = collectAssetUses(withPortal, 'shot-portal')
  assert.ok(portalUses.some(item => item.role === 'worldSfx[0]' && item.filename === 'portal.png'))
  assert.ok(!portalUses.some(item => item.role === 'worldSfx[1]'))
  assert.equal(classifyUrl('https://evil.example/a.glb'), 'external')
  assert.equal(classifyUrl('blob:temp'), 'transient')
  assert.equal(classifyUrl('/api/v1/file/hero.glb?workspace=film'), 'gallery')
})

test('template wrapper is not a package and unknown fields plus cinema are surfaced', () => {
  const wrapper = { kind: TEMPLATE_KIND, version: 1, id: 'user-1', title: 'Cafe', document: shot('Cafe') }
  assert.equal(isTemplateWrapper(wrapper), true)
  assert.equal(isTemplateWrapper(shot('Cafe')), false)
  const flagged = { ...shot('X'), customRendererFlag: true, cinemaExtension: 'tools/cinema', slots: [{ ...shot('X').slots[0], mysteryRig: { bones: 2 } }] }
  const unknown = collectUnknownFields(flagged)
  assert.ok(unknown.includes('customRendererFlag'))
  assert.ok(unknown.some(item => item.includes('mysteryRig')))
  assert.equal(cinemaExtensionOf(flagged), 'tools/cinema')
  assert.ok(documentIssues(flagged, 1).some(item => item.code === 'cinema_extension'))
  assert.ok(documentIssues({ ...shot('Net'), slots: [{ ...shot('Net').slots[0], sourceUrl: 'https://evil.example/a.glb', sourceRef: { ...glb, url: 'https://evil.example/a.glb' } }] }, 1)
    .some(item => item.code === 'external_link'))
})

test('preflight detects template JSON, traversal, tamper and allows picker reassignment', async () => {
  const template = new TextEncoder().encode(JSON.stringify({ kind: TEMPLATE_KIND, version: 1, id: 'x', title: 'Cafe', document: shot('Cafe') }))
  const asTemplate = await preflightBytes(template, 'cafe.world3d.template.json')
  assert.equal(asTemplate.ok, false)
  assert.ok(asTemplate.issues.some(item => item.code === 'template'))

  const glbBytes = new TextEncoder().encode('glb-shared')
  const digest = await sha256Hex(glbBytes)
  const packedShot = JSON.parse(JSON.stringify(shot('One')))
  packedShot.slots[0].sourceUrl = `media/${digest}.glb`
  packedShot.slots[0].sourceRef = { workspaceId: 'package', filename: 'hero.glb', url: `media/${digest}.glb`, assetId: `sha256:${digest}` }
  const zip = new JSZip()
  zip.file('package.json', JSON.stringify({
    kind: PACKAGE_KIND, schema: PACKAGE_KIND, schema_version: 1, title: 'One',
    documents: [{ id: 'shot-1', role: 'shot', path: 'documents/shot-1.json', sha256: 'x' }],
    assets: [{ sha256: digest, filename: 'hero.glb', path: `media/${digest}.glb`, kind: 'model3d' }],
  }))
  zip.file('documents/shot-1.json', JSON.stringify(packedShot))
  zip.file(`media/${digest}.glb`, 'not-the-glb')
  zip.file('tools/cinema.js', '/* unknown cinema runtime */')
  const bytes = await zip.generateAsync({ type: 'uint8array' })
  const report = await preflightBytes(bytes)
  assert.equal(report.ok, false)
  assert.ok(report.issues.some(item => item.code === 'tampered_asset' && item.repair))
  assert.ok(report.issues.some(item => item.code === 'cinema_extension'))
  assert.throws(() => safeZipMember('../evil.glb'))
  assert.throws(() => safeZipMember('/tmp/evil.glb'))
  assert.throws(() => safeZipMember('media/../../passwd'))
  const repairs = repairAssets(report)
  assert.equal(repairs.length, 1)
  assert.equal(canImport(report, []), false)
  const entry = pickerToReassign(digest, {
    name: 'hero.glb', type: 'model3d', mode: null, size: 10, created_at: 0,
    url: '/api/v1/file/hero.glb?workspace=lab', workspace_id: 'lab', asset_id: 'asset_lab',
  }, 'lab')
  assert.equal(canImport(report, [entry.sha256]), false) // still has traversal
  assert.ok(JSON.parse(encodeReassign([entry]))[0].filename === 'hero.glb')
})
