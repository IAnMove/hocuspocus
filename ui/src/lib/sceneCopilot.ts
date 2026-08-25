import type { Scene, SceneKeyframe, SceneLayer } from '../types'
import { buildDriftKeyframes } from './sceneNarrative'

export type SceneCopilotScope = 'layer' | 'scene'
export type SceneMotionPreset = 'thinking_drift' | 'living_drift' | 'run_bob' | 'float'
export type SceneEditOperation =
  | { op: 'set_transform'; layerId: string; patch: Partial<Pick<SceneLayer['transform'], 'x' | 'y' | 'scale' | 'opacity' | 'rotation'>> }
  | { op: 'set_effects'; layerId: string; patch: NonNullable<SceneLayer['effects']> }
  | { op: 'set_parallax'; layerId: string; value: number }
  | { op: 'set_orientation'; layerId: string; rotationX?: number; rotationY?: number }
  | { op: 'set_motion_preset'; layerId: string; preset: SceneMotionPreset; duration?: number }
  | { op: 'set_keyframes'; layerId: string; keyframes: SceneKeyframe[] }

export type SceneCopilotProposal = { summary: string; scope: SceneCopilotScope; operations: SceneEditOperation[]; needsConfirmation: boolean }

const record = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value)
const number = (value: unknown, min: number, max: number, label: string) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${label} must be a finite number.`)
  return Math.max(min, Math.min(max, value))
}
const objectFrom = (text: string) => {
  const raw = text.match(/```(?:json)?\s*([\s\S]*?)```/i)?.[1] ?? text
  const start = raw.indexOf('{'); const end = raw.lastIndexOf('}')
  if (start < 0 || end <= start) throw new Error('The copilot did not return a JSON object.')
  return JSON.parse(raw.slice(start, end + 1)) as unknown
}
const layerById = (scene: Scene, id: string) => {
  const layer = scene.layers.find(item => item.id === id)
  if (!layer) throw new Error('The selected layer no longer exists.')
  return layer
}

export const SCENE_COPILOT_JSON_SCHEMA: Record<string, unknown> = {
  type: 'object', additionalProperties: false, required: ['summary', 'scope', 'operations', 'needsConfirmation'],
  properties: {
    summary: { type: 'string', maxLength: 500 }, scope: { const: 'layer' }, needsConfirmation: { type: 'boolean' },
    operations: { type: 'array', minItems: 1, maxItems: 6, items: { type: 'object', additionalProperties: false, required: ['op', 'layerId'], properties: { op: { enum: ['set_transform', 'set_effects', 'set_parallax', 'set_orientation', 'set_motion_preset', 'set_keyframes'] }, layerId: { type: 'string' }, patch: { type: 'object' }, value: { type: 'number' }, rotationX: { type: 'number' }, rotationY: { type: 'number' }, preset: { enum: ['thinking_drift', 'living_drift', 'run_bob', 'float'] }, duration: { type: 'number' }, keyframes: { type: 'array', minItems: 2, maxItems: 16 } } } },
  },
}

export const buildSceneCopilotSystemPrompt = (scene: Scene, selected: SceneLayer) => [
  'You are HocusPocus selected-item 3D scene copilot. Return one JSON object only.',
  'Edit ONLY the selected layer. scope must be layer; every layerId must match it exactly.',
  'Never generate assets, alter the camera/other layers, delete, change global duration, relationships, or invent rig clips.',
  'Allowed ops: set_transform, set_effects, set_parallax, set_orientation (model3d only), set_motion_preset, set_keyframes.',
  'Use 1–3 restrained operations. Emotional language maps to transform, motion and effects.',
  `SCENE=${JSON.stringify({ duration: scene.duration, fps: scene.fps ?? 30, width: scene.width, height: scene.height, layers: scene.layers.map(layer => ({ id: layer.id, name: layer.name, type: layer.type })) })}`,
  `SELECTED=${JSON.stringify({ id: selected.id, name: selected.name, type: selected.type, transform: selected.transform, animation: selected.animation, effects: selected.effects ?? {}, parallax: selected.parallax ?? 1, limitation: selected.type === 'model3d' ? 'No invented rig clip.' : undefined })}`,
].join('\n')

const numericPatch = (raw: unknown, allowed: readonly string[], label: string) => {
  if (!record(raw)) throw new Error(`${label} must be an object.`)
  const values = Object.entries(raw).filter(([key]) => allowed.includes(key))
  if (!values.length) throw new Error(`${label} has no supported properties.`)
  return values
}

export const parseSceneCopilotProposal = (text: string, scene: Scene, selectedLayerId: string): SceneCopilotProposal => {
  const raw = objectFrom(text)
  if (!record(raw) || raw.scope !== 'layer' || typeof raw.summary !== 'string' || typeof raw.needsConfirmation !== 'boolean' || !Array.isArray(raw.operations) || raw.operations.length < 1 || raw.operations.length > 6) throw new Error('The copilot proposal has an invalid envelope.')
  const selected = layerById(scene, selectedLayerId)
  if (selected.locked) throw new Error('Unlock the selected layer before asking the copilot to modify it.')
  const operations = raw.operations.map((value, index): SceneEditOperation => {
    if (!record(value) || value.layerId !== selectedLayerId || typeof value.op !== 'string') throw new Error(`Operation ${index + 1} must target only the selected layer.`)
    if (value.op === 'set_transform') {
      const patch: Partial<Pick<SceneLayer['transform'], 'x' | 'y' | 'scale' | 'opacity' | 'rotation'>> = {}
      for (const [key, rawValue] of numericPatch(value.patch, ['x', 'y', 'scale', 'opacity', 'rotation'], 'transform patch')) {
        if (key === 'x' || key === 'y') patch[key] = number(rawValue, -500, 500, `transform.${key}`)
        if (key === 'scale') patch.scale = number(rawValue, .01, 20, 'transform.scale')
        if (key === 'opacity') patch.opacity = number(rawValue, 0, 1, 'transform.opacity')
        if (key === 'rotation') patch.rotation = number(rawValue, -36000, 36000, 'transform.rotation')
      }
      return { op: 'set_transform', layerId: selectedLayerId, patch }
    }
    if (value.op === 'set_effects') {
      const patch: NonNullable<SceneLayer['effects']> = {}
      for (const [key, rawValue] of numericPatch(value.patch, ['blur', 'brightness', 'contrast', 'saturation', 'hue', 'glow', 'shadow'], 'effects patch')) {
        const limits: Record<string, [number, number]> = { blur: [0, 3], brightness: [0, 3], contrast: [0, 3], saturation: [0, 4], hue: [-180, 180], glow: [0, 5], shadow: [0, 8] }
        patch[key as keyof typeof patch] = number(rawValue, ...limits[key], `effects.${key}`) as never
      }
      return { op: 'set_effects', layerId: selectedLayerId, patch }
    }
    if (value.op === 'set_parallax') return { op: 'set_parallax', layerId: selectedLayerId, value: number(value.value, 0, 4, 'parallax') }
    if (value.op === 'set_orientation') {
      if (selected.type !== 'model3d') throw new Error('Orientation is only supported by selected 3D model layers.')
      return { op: 'set_orientation', layerId: selectedLayerId, rotationX: value.rotationX === undefined ? undefined : number(value.rotationX, 1, 179, 'orientation.rotationX'), rotationY: value.rotationY === undefined ? undefined : number(value.rotationY, -3600, 3600, 'orientation.rotationY') }
    }
    if (value.op === 'set_motion_preset') {
      if (!['thinking_drift', 'living_drift', 'run_bob', 'float'].includes(String(value.preset))) throw new Error('Unsupported motion preset.')
      return { op: 'set_motion_preset', layerId: selectedLayerId, preset: value.preset as SceneMotionPreset, duration: value.duration === undefined ? undefined : number(value.duration, 1, 60, 'motion.duration') }
    }
    if (value.op === 'set_keyframes') {
      if (!Array.isArray(value.keyframes) || value.keyframes.length < 2 || value.keyframes.length > 16) throw new Error('Keyframes must contain 2–16 points.')
      return { op: 'set_keyframes', layerId: selectedLayerId, keyframes: value.keyframes.map((frame, frameIndex) => {
        if (!record(frame)) throw new Error(`Keyframe ${frameIndex + 1} is invalid.`)
        return { id: `${selectedLayerId}-copilot-${frameIndex}`, time: number(frame.time, 0, 3600, 'keyframe.time'), x: number(frame.x, -500, 500, 'keyframe.x'), y: number(frame.y, -500, 500, 'keyframe.y'), scale: number(frame.scale, .01, 20, 'keyframe.scale'), opacity: number(frame.opacity, 0, 1, 'keyframe.opacity'), rotation: number(frame.rotation, -36000, 36000, 'keyframe.rotation'), curve: ['linear', 'ease', 'dramatic', 'bounce'].includes(String(frame.curve)) ? frame.curve as SceneKeyframe['curve'] : selected.animation.curve }
      }).sort((a, b) => a.time - b.time) }
    }
    throw new Error(`Unsupported operation: ${value.op}`)
  })
  return { summary: raw.summary.trim().slice(0, 500), scope: 'layer', operations, needsConfirmation: raw.needsConfirmation }
}

const motion = (layer: SceneLayer, preset: SceneMotionPreset, duration?: number): SceneLayer => {
  const seconds = duration ?? Math.max(10, layer.animation.duration)
  const start = { x: layer.transform.x, y: layer.transform.y, scale: layer.transform.scale, opacity: layer.transform.opacity, rotation: layer.transform.rotation ?? 0 }
  const settings = preset === 'thinking_drift' ? { dx: 5, dy: -3, bob: .7, pulse: .012, rotation: .45 } : preset === 'run_bob' ? { dx: 1, dy: 0, bob: .9, pulse: .006, rotation: 1.4 } : preset === 'float' ? { dx: 2, dy: -1, bob: 1, pulse: .014, rotation: .65 } : { dx: 3, dy: -1, bob: .35, pulse: .006, rotation: .25 }
  const end = { ...start, x: start.x + settings.dx, y: start.y + settings.dy, scale: start.scale * 1.02 }
  const keyframes = buildDriftKeyframes(`${layer.id}-${preset}`, seconds, start, end, settings)
  return { ...layer, transform: { ...layer.transform, ...end }, animation: { ...layer.animation, start: keyframes[0], end: keyframes[keyframes.length - 1], keyframes, duration: seconds, trimEnd: seconds, curve: 'ease' } }
}

export const applySceneCopilotProposal = (scene: Scene, proposal: SceneCopilotProposal): Scene => {
  const layers = scene.layers.map(layer => proposal.operations.reduce((current, operation) => {
    if (operation.layerId !== current.id) return current
    if (operation.op === 'set_transform') {
      const transform = { ...current.transform, ...operation.patch }
      const dx = transform.x - current.transform.x; const dy = transform.y - current.transform.y
      return { ...current, transform, animation: { ...current.animation, start: { ...current.animation.start, x: current.animation.start.x + dx, y: current.animation.start.y + dy }, end: { ...current.animation.end, x: current.animation.end.x + dx, y: current.animation.end.y + dy }, keyframes: current.animation.keyframes?.map(frame => ({ ...frame, x: frame.x + dx, y: frame.y + dy })) } }
    }
    if (operation.op === 'set_effects') return { ...current, effects: { ...current.effects, ...operation.patch } }
    if (operation.op === 'set_parallax') return current.type === 'camera' ? current : { ...current, parallax: operation.value }
    if (operation.op === 'set_orientation') return { ...current, transform: { ...current.transform, ...(operation.rotationX === undefined ? {} : { rotationX: operation.rotationX }), ...(operation.rotationY === undefined ? {} : { rotationY: operation.rotationY }) } }
    if (operation.op === 'set_motion_preset') return motion(current, operation.preset, operation.duration)
    const first = operation.keyframes[0]; const last = operation.keyframes[operation.keyframes.length - 1]
    return { ...current, transform: { ...current.transform, x: last.x, y: last.y, scale: last.scale, opacity: last.opacity, rotation: last.rotation }, animation: { ...current.animation, start: first, end: last, keyframes: operation.keyframes, duration: Math.max(current.animation.duration, last.time), trimEnd: Math.max(current.animation.duration, last.time) } }
  }, layer))
  return { ...scene, duration: Math.max(scene.duration, ...layers.map(layer => layer.animation.duration)), layers }
}

export const describeSceneCopilotProposal = (scene: Scene, proposal: SceneCopilotProposal) => proposal.operations.map(operation => {
  const label = layerById(scene, operation.layerId).name
  if (operation.op === 'set_transform') return `${label}: ${Object.entries(operation.patch).map(([key, value]) => `${key} → ${value}`).join(', ')}`
  if (operation.op === 'set_effects') return `${label}: ${Object.entries(operation.patch).map(([key, value]) => `${key} → ${value}`).join(', ')}`
  if (operation.op === 'set_motion_preset') return `${label}: ${operation.preset.replace('_', ' ')} motion`
  if (operation.op === 'set_keyframes') return `${label}: ${operation.keyframes.length} keyframes`
  return `${label}: ${operation.op.replaceAll('_', ' ')}`
})
