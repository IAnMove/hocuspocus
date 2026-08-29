import assert from 'node:assert/strict'
import test from 'node:test'
import { applySceneCopilotProposal, parseSceneCopilotProposal } from '../src/lib/sceneCopilot.ts'

const scene = { version: 1, name: 'Thought', width: 1280, height: 720, fps: 30, duration: 10, layers: [{ id: 'hero', name: 'Hero', type: 'model3d', source: '/hero.glb', visible: true, z: 10, transform: { x: 67, y: 54, scale: .9, opacity: 1, rotation: 0 }, animation: { start: { x: 67, y: 54, scale: .9 }, end: { x: 67, y: 54, scale: .9 }, duration: 10, curve: 'ease' } }] }
const sceneWithCamera = { ...scene, layers: [...scene.layers, { id: 'camera', name: 'Camera', type: 'camera', source: '', visible: true, z: 20, transform: { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 }, animation: { start: { x: 50, y: 50, scale: 1 }, end: { x: 50, y: 50, scale: 1 }, duration: 10, curve: 'ease' } }] }

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
  assert.throws(() => parseSceneCopilotProposal(JSON.stringify({ summary: 'Run', scope: 'layer', needsConfirmation: false, operations: [{ op: 'set_rig_clip', layerId: 'hero' }] }), scene, 'hero'), /verified clips/)
})

test('copilot accepts only a verified rig clip for the selected 3D model', () => {
  const proposal = parseSceneCopilotProposal(JSON.stringify({ summary: 'Use the real run clip.', scope: 'layer', needsConfirmation: false, operations: [{ op: 'set_rig_clip', layerId: 'hero', clip: 'Run', loop: true, speed: 1.1 }] }), scene, 'hero', 'layer', ['Idle', 'Run'])
  assert.equal(applySceneCopilotProposal(scene, proposal).layers[0].animation.clip, 'Run')
  assert.throws(() => parseSceneCopilotProposal(JSON.stringify({ summary: 'Invent it.', scope: 'layer', needsConfirmation: false, operations: [{ op: 'set_rig_clip', layerId: 'hero', clip: 'Sprint' }] }), scene, 'hero', 'layer', ['Idle', 'Run']), /verified clips/)
})

test('copilot can tune a selected loop seam cover without touching another layer', () => {
  const loop = { ...scene, layers: [{ ...scene.layers[0], type: 'image', strip: { enabled: true, count: 4, spacing: 100, direction: 'left', speed: 12, seamOccluder: { enabled: true, kind: 'tree', scale: 1, opacity: .82 } } }] }
  const proposal = parseSceneCopilotProposal(JSON.stringify({ summary: 'Use a smaller lamp.', scope: 'layer', needsConfirmation: false, operations: [{ op: 'set_seam_occluder', layerId: 'hero', enabled: true, kind: 'lamp', scale: .7, opacity: .65 }] }), loop, 'hero')
  const cover = applySceneCopilotProposal(loop, proposal).layers[0].strip.seamOccluder
  assert.deepEqual(cover, { enabled: true, kind: 'lamp', scale: .7, opacity: .65 })
  assert.throws(() => parseSceneCopilotProposal(JSON.stringify({ summary: 'Add seam.', scope: 'layer', needsConfirmation: false, operations: [{ op: 'set_seam_occluder', layerId: 'hero', enabled: true }] }), scene, 'hero'), /repeating layer/)
})

test('scene scope is limited to camera motion and a global grade', () => {
  const proposal = parseSceneCopilotProposal(JSON.stringify({ summary: 'A cool drifting thought.', scope: 'scene', needsConfirmation: true, operations: [{ op: 'set_camera_motion', layerId: 'camera', preset: 'drift', duration: 12 }, { op: 'set_scene_grade', layerId: 'scene', palette: 'cool', mood: 'dreamy', intensity: 2 }] }), sceneWithCamera, undefined, 'scene')
  const next = applySceneCopilotProposal(sceneWithCamera, proposal)
  const hero = next.layers.find(layer => layer.id === 'hero')
  const camera = next.layers.find(layer => layer.id === 'camera')
  assert.equal(hero.source, '/hero.glb')
  assert.equal(hero.transform.x, 67)
  assert.equal(hero.effects?.hue, 12)
  assert.ok(camera.animation.keyframes.length >= 5)
})

test('scene scope rejects transforms and non-camera targets', () => {
  assert.throws(() => parseSceneCopilotProposal(JSON.stringify({ summary: 'Move hero', scope: 'scene', needsConfirmation: false, operations: [{ op: 'set_transform', layerId: 'hero', patch: { x: 20 } }] }), sceneWithCamera, undefined, 'scene'), /does not allow/)
  assert.throws(() => parseSceneCopilotProposal(JSON.stringify({ summary: 'Camera', scope: 'scene', needsConfirmation: false, operations: [{ op: 'set_camera_motion', layerId: 'hero', preset: 'push' }] }), sceneWithCamera, undefined, 'scene'), /camera layer/)
})

test('scene scope validates confirmed relationships between existing visual layers', () => {
  const richer = { ...sceneWithCamera, layers: [...sceneWithCamera.layers, { id: 'halo', name: 'Halo', type: 'image', source: '/halo.png', visible: true, z: 12, transform: { x: 67, y: 54, scale: 1, opacity: 1, rotation: 0 }, animation: { start: { x: 67, y: 54, scale: 1 }, end: { x: 67, y: 54, scale: 1 }, duration: 10, curve: 'ease' } }] }
  const proposal = parseSceneCopilotProposal(JSON.stringify({ summary: 'Attach halo.', scope: 'scene', needsConfirmation: true, operations: [{ op: 'set_relationship', layerId: 'halo', relationship: 'follow', targetLayerId: 'hero', offsetX: 0, offsetY: -4, strength: 1 }] }), richer, undefined, 'scene')
  const halo = applySceneCopilotProposal(richer, proposal).layers.find(layer => layer.id === 'halo')
  assert.equal(halo.relationship?.type, 'follow')
  assert.equal(halo.relationship?.targetLayerId, 'hero')
  assert.throws(() => parseSceneCopilotProposal(JSON.stringify({ summary: 'Attach halo.', scope: 'scene', needsConfirmation: false, operations: [{ op: 'set_relationship', layerId: 'halo', relationship: 'follow', targetLayerId: 'hero' }] }), richer, undefined, 'scene'), /require confirmation/)
})
