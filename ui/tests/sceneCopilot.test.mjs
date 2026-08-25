import assert from 'node:assert/strict'
import test from 'node:test'
import { applySceneCopilotProposal, parseSceneCopilotProposal } from '../src/lib/sceneCopilot.ts'

const scene = { version: 1, name: 'Thought', width: 1280, height: 720, fps: 30, duration: 10, layers: [{ id: 'hero', name: 'Hero', type: 'model3d', source: '/hero.glb', visible: true, z: 10, transform: { x: 67, y: 54, scale: .9, opacity: 1, rotation: 0 }, animation: { start: { x: 67, y: 54, scale: .9 }, end: { x: 67, y: 54, scale: .9 }, duration: 10, curve: 'ease' } }] }

test('copilot rejects an operation outside the selected layer', () => {
  assert.throws(() => parseSceneCopilotProposal(JSON.stringify({ summary: 'Move camera', scope: 'layer', needsConfirmation: false, operations: [{ op: 'set_transform', layerId: 'camera', patch: { x: 20 } }] }), scene, 'hero'), /selected layer/)
})

test('copilot validates and applies normal editable scene operations', () => {
  const proposal = parseSceneCopilotProposal(JSON.stringify({ summary: 'Make room for voice.', scope: 'layer', needsConfirmation: false, operations: [{ op: 'set_transform', layerId: 'hero', patch: { x: 54 } }, { op: 'set_motion_preset', layerId: 'hero', preset: 'thinking_drift', duration: 10 }, { op: 'set_effects', layerId: 'hero', patch: { glow: 1.2 } }] }), scene, 'hero')
  const hero = applySceneCopilotProposal(scene, proposal).layers[0]
  assert.equal(hero.transform.x, 59)
  assert.equal(hero.effects?.glow, 1.2)
  assert.ok(hero.animation.keyframes.length >= 5)
})

test('copilot rejects invented rig operations', () => {
  assert.throws(() => parseSceneCopilotProposal(JSON.stringify({ summary: 'Run', scope: 'layer', needsConfirmation: false, operations: [{ op: 'set_rig_clip', layerId: 'hero' }] }), scene, 'hero'), /Unsupported operation/)
})
