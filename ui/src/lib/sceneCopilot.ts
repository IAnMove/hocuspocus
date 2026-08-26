import type { Scene, SceneKeyframe, SceneLayer } from '../types'
import { buildDriftKeyframes } from './sceneNarrative'
import { resolveSceneGrade } from './sceneGrade'

export type SceneCopilotScope = 'layer' | 'scene'
export type SceneMotionPreset = 'thinking_drift' | 'living_drift' | 'run_bob' | 'float'
export type SceneEditOperation =
  | { op: 'set_transform'; layerId: string; patch: Partial<Pick<SceneLayer['transform'], 'x' | 'y' | 'scale' | 'opacity' | 'rotation'>> }
  | { op: 'set_effects'; layerId: string; patch: NonNullable<SceneLayer['effects']> }
  | { op: 'set_parallax'; layerId: string; value: number }
  | { op: 'set_seam_occluder'; layerId: string; enabled: boolean; kind?: 'pole' | 'lamp' | 'tree' | 'column'; scale?: number; opacity?: number }
  | { op: 'set_orientation'; layerId: string; rotationX?: number; rotationY?: number }
  | { op: 'set_motion_preset'; layerId: string; preset: SceneMotionPreset; duration?: number }
  | { op: 'set_keyframes'; layerId: string; keyframes: SceneKeyframe[] }
  | { op: 'set_rig_clip'; layerId: string; clip: string; loop?: boolean; speed?: number }
  | { op: 'set_camera_motion'; layerId: string; preset: 'restrained' | 'push' | 'drift'; duration?: number }
  | { op: 'set_scene_grade'; layerId: 'scene'; palette: 'natural' | 'cool' | 'warm' | 'neon'; mood?: 'calm' | 'tense' | 'dreamy' | 'heroic'; intensity?: 1 | 2 | 3 }
  | { op: 'set_relationship'; layerId: string; relationship: 'parent' | 'follow' | 'lookAt' | 'none'; targetLayerId?: string; offsetX?: number; offsetY?: number; strength?: number; rotationOffset?: number }

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
const wouldCreateRelationshipCycle = (scene: Scene, layerId: string, targetId: string) => {
  let cursor: string | undefined = targetId
  const seen = new Set<string>()
  while (cursor && !seen.has(cursor)) {
    if (cursor === layerId) return true
    seen.add(cursor)
    cursor = scene.layers.find(layer => layer.id === cursor)?.relationship?.targetLayerId
  }
  return false
}

export const SCENE_COPILOT_JSON_SCHEMA: Record<string, unknown> = {
  type: 'object', additionalProperties: false, required: ['summary', 'scope', 'operations', 'needsConfirmation'],
  properties: {
    summary: { type: 'string', maxLength: 500 }, scope: { enum: ['layer', 'scene'] }, needsConfirmation: { type: 'boolean' },
    operations: { type: 'array', minItems: 1, maxItems: 6, items: { type: 'object', additionalProperties: false, required: ['op', 'layerId'], properties: { op: { enum: ['set_transform', 'set_effects', 'set_parallax', 'set_seam_occluder', 'set_orientation', 'set_motion_preset', 'set_keyframes', 'set_rig_clip', 'set_camera_motion', 'set_scene_grade', 'set_relationship'] }, layerId: { type: 'string' }, patch: { type: 'object' }, value: { type: 'number' }, enabled: { type: 'boolean' }, kind: { enum: ['pole', 'lamp', 'tree', 'column'] }, scale: { type: 'number' }, opacity: { type: 'number' }, rotationX: { type: 'number' }, rotationY: { type: 'number' }, preset: { enum: ['thinking_drift', 'living_drift', 'run_bob', 'float', 'restrained', 'push', 'drift'] }, duration: { type: 'number' }, keyframes: { type: 'array', minItems: 2, maxItems: 16 }, clip: { type: 'string' }, loop: { type: 'boolean' }, speed: { type: 'number' }, palette: { enum: ['natural', 'cool', 'warm', 'neon'] }, mood: { enum: ['calm', 'tense', 'dreamy', 'heroic'] }, intensity: { enum: [1, 2, 3] }, relationship: { enum: ['parent', 'follow', 'lookAt', 'none'] }, targetLayerId: { type: 'string' }, offsetX: { type: 'number' }, offsetY: { type: 'number' }, strength: { type: 'number' }, rotationOffset: { type: 'number' } } } },
  },
}

export const buildSceneCopilotSystemPrompt = (scene: Scene, selected: SceneLayer, verifiedClips: string[] = []) => [
  'You are HocusPocus selected-item 3D scene copilot. Return one JSON object only.',
  'Edit ONLY the selected layer. scope must be layer; every layerId must match it exactly.',
  'Never generate assets, alter the camera/other layers, delete, change global duration, relationships, or invent rig clips.',
  `Allowed ops: set_transform, set_effects, set_parallax, set_seam_occluder (only a selected repeating visual layer), set_orientation (model3d only), set_motion_preset, set_keyframes${verifiedClips.length ? ', set_rig_clip (only from VERIFIED_CLIPS)' : ''}.`,
  'Use 1–3 restrained operations. Emotional language maps to transform, motion and effects.',
  `SCENE=${JSON.stringify({ duration: scene.duration, fps: scene.fps ?? 30, width: scene.width, height: scene.height, layers: scene.layers.map(layer => ({ id: layer.id, name: layer.name, type: layer.type })) })}`,
  `SELECTED=${JSON.stringify({ id: selected.id, name: selected.name, type: selected.type, transform: selected.transform, animation: selected.animation, effects: selected.effects ?? {}, parallax: selected.parallax ?? 1, limitation: selected.type === 'model3d' ? 'No invented rig clip.' : undefined })}`,
  `VERIFIED_CLIPS=${JSON.stringify(verifiedClips)}`,
].join('\n')

/** Scene-wide requests expose only camera movement, visual grade and explicit layer relationships. */
export const buildSceneScopeCopilotSystemPrompt = (scene: Scene) => [
  'You are HocusPocus scene-level 3D copilot. Return one JSON object only.',
  'scope must be scene. You may make only a restrained camera move, visual grade, or explicit relationship between existing visual layers.',
  'Allowed ops: set_camera_motion (existing camera), set_scene_grade (layerId "scene"), set_relationship (existing non-camera layers only).',
  'Never add, remove, replace, move, transform, animate or reparent assets/layers except the declared relationship. Never change duration, fps, sources, rigs, or audio.',
  'Use 1–2 operations. needsConfirmation must be true for every set_relationship.',
  `SCENE=${JSON.stringify({ duration: scene.duration, fps: scene.fps ?? 30, width: scene.width, height: scene.height, cameras: scene.layers.filter(layer => layer.type === 'camera').map(layer => ({ id: layer.id, name: layer.name, animation: layer.animation })), visualLayers: scene.layers.filter(layer => layer.type !== 'camera').map(layer => ({ id: layer.id, name: layer.name, type: layer.type, relationship: layer.relationship, effects: layer.effects ?? {} })) })}`,
].join('\n')

const numericPatch = (raw: unknown, allowed: readonly string[], label: string) => {
  if (!record(raw)) throw new Error(`${label} must be an object.`)
  const values = Object.entries(raw).filter(([key]) => allowed.includes(key))
  if (!values.length) throw new Error(`${label} has no supported properties.`)
  return values
}

export const parseSceneCopilotProposal = (text: string, scene: Scene, selectedLayerId?: string, expectedScope: SceneCopilotScope = 'layer', verifiedClips: string[] = []): SceneCopilotProposal => {
  const raw = objectFrom(text)
  if (!record(raw) || raw.scope !== expectedScope || typeof raw.summary !== 'string' || typeof raw.needsConfirmation !== 'boolean' || !Array.isArray(raw.operations) || raw.operations.length < 1 || raw.operations.length > 6) throw new Error('The copilot proposal has an invalid envelope.')
  if (expectedScope === 'scene') {
    const operations = raw.operations.map((value, index): SceneEditOperation => {
      if (!record(value) || typeof value.op !== 'string' || typeof value.layerId !== 'string') throw new Error(`Operation ${index + 1} is invalid.`)
      if (value.op === 'set_camera_motion') {
        const camera = layerById(scene, value.layerId)
        if (camera.type !== 'camera') throw new Error('Scene camera motion must target an existing camera layer.')
        if (!['restrained', 'push', 'drift'].includes(String(value.preset))) throw new Error('Unsupported scene camera preset.')
        return { op: 'set_camera_motion', layerId: camera.id, preset: value.preset as 'restrained' | 'push' | 'drift', duration: value.duration === undefined ? undefined : number(value.duration, 1, 60, 'camera.duration') }
      }
      if (value.op === 'set_scene_grade') {
        if (value.layerId !== 'scene' || !['natural', 'cool', 'warm', 'neon'].includes(String(value.palette))) throw new Error('Scene grade must target scene and use a supported palette.')
        if (value.mood !== undefined && !['calm', 'tense', 'dreamy', 'heroic'].includes(String(value.mood))) throw new Error('Unsupported scene mood.')
        const intensity = value.intensity === undefined ? undefined : number(value.intensity, 1, 3, 'grade.intensity') as 1 | 2 | 3
        return { op: 'set_scene_grade', layerId: 'scene', palette: value.palette as 'natural' | 'cool' | 'warm' | 'neon', mood: value.mood as 'calm' | 'tense' | 'dreamy' | 'heroic' | undefined, intensity }
      }
      if (value.op === 'set_relationship') {
        if (!raw.needsConfirmation) throw new Error('Scene relationships always require confirmation.')
        const layer = layerById(scene, value.layerId)
        if (layer.type === 'camera' || layer.locked) throw new Error('Relationships require an unlocked visual layer.')
        if (!['parent', 'follow', 'lookAt', 'none'].includes(String(value.relationship))) throw new Error('Unsupported relationship.')
        if (value.relationship === 'none') return { op: 'set_relationship', layerId: layer.id, relationship: 'none' }
        if (typeof value.targetLayerId !== 'string') throw new Error('A relationship target is required.')
        const target = layerById(scene, value.targetLayerId)
        if (target.type === 'camera' || target.id === layer.id || wouldCreateRelationshipCycle(scene, layer.id, target.id)) throw new Error('The relationship target is not valid.')
        return { op: 'set_relationship', layerId: layer.id, relationship: value.relationship as 'parent' | 'follow' | 'lookAt', targetLayerId: target.id, offsetX: value.offsetX === undefined ? 0 : number(value.offsetX, -500, 500, 'relationship.offsetX'), offsetY: value.offsetY === undefined ? 0 : number(value.offsetY, -500, 500, 'relationship.offsetY'), strength: value.strength === undefined ? 1 : number(value.strength, 0, 1, 'relationship.strength'), rotationOffset: value.rotationOffset === undefined ? 0 : number(value.rotationOffset, -360, 360, 'relationship.rotationOffset') }
      }
      throw new Error(`Scene scope does not allow ${value.op}.`)
    })
    return { summary: raw.summary.trim().slice(0, 500), scope: 'scene', operations, needsConfirmation: raw.needsConfirmation }
  }
  if (!selectedLayerId) throw new Error('A selected layer is required for layer scope.')
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
    if (value.op === 'set_seam_occluder') {
      if (!selected.strip?.enabled) throw new Error('A seam cover can only be changed on the selected repeating layer.')
      if (typeof value.enabled !== 'boolean') throw new Error('seam.enabled must be boolean.')
      if (value.kind !== undefined && !['pole', 'lamp', 'tree', 'column'].includes(String(value.kind))) throw new Error('Unsupported seam cover kind.')
      return { op: 'set_seam_occluder', layerId: selectedLayerId, enabled: value.enabled, kind: value.kind as 'pole' | 'lamp' | 'tree' | 'column' | undefined, scale: value.scale === undefined ? undefined : number(value.scale, .45, 1.8, 'seam.scale'), opacity: value.opacity === undefined ? undefined : number(value.opacity, .2, 1, 'seam.opacity') }
    }
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
        return { id: `${selectedLayerId}-copilot-${frameIndex}`, time: number(frame.time, 0, 3600, 'keyframe.time'), x: number(frame.x, -500, 500, 'keyframe.x'), y: number(frame.y, -500, 500, 'keyframe.y'), scale: number(frame.scale, .01, 20, 'keyframe.scale'), opacity: number(frame.opacity, 0, 1, 'keyframe.opacity'), rotation: number(frame.rotation, -36000, 36000, 'keyframe.rotation'), curve: ['linear', 'ease', 'dramatic', 'bounce', 'hold'].includes(String(frame.curve)) ? frame.curve as SceneKeyframe['curve'] : selected.animation.curve }
      }).sort((a, b) => a.time - b.time) }
    }
    if (value.op === 'set_rig_clip') {
      if (selected.type !== 'model3d' || typeof value.clip !== 'string' || !verifiedClips.includes(value.clip)) throw new Error('Rig clip must be one of the verified clips for the selected 3D model.')
      return { op: 'set_rig_clip', layerId: selectedLayerId, clip: value.clip, loop: value.loop === undefined ? true : Boolean(value.loop), speed: value.speed === undefined ? 1 : number(value.speed, .05, 8, 'clip.speed') }
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
  if (proposal.scope === 'scene') {
    return proposal.operations.reduce((currentScene, operation) => {
      if (operation.op === 'set_camera_motion') {
        return { ...currentScene, layers: currentScene.layers.map(layer => {
          if (layer.id !== operation.layerId) return layer
          const duration = operation.duration ?? Math.max(10, layer.animation.duration, currentScene.duration)
          const start = { x: layer.animation.start.x, y: layer.animation.start.y, scale: layer.animation.start.scale, opacity: layer.animation.start.opacity ?? 1, rotation: layer.animation.start.rotation ?? 0 }
          const end = operation.preset === 'push' ? { ...start, scale: start.scale + .1 } : operation.preset === 'drift' ? { ...start, x: start.x + 2, y: start.y - 1, scale: start.scale + .03 } : { ...start, scale: start.scale + .025 }
          const keyframes = buildDriftKeyframes(`${layer.id}-scene-${operation.preset}`, duration, start, end, operation.preset === 'drift' ? { bob: .35, pulse: .006 } : { pulse: .002 })
          return { ...layer, transform: { ...layer.transform, ...end }, animation: { ...layer.animation, start: keyframes[0], end: keyframes[keyframes.length - 1], keyframes, duration, trimEnd: duration, curve: 'ease' } }
        }) }
      }
      if (operation.op === 'set_scene_grade') {
        // Editing, so a neutral palette must write explicit neutral values —
        // otherwise asking for 'natural' could never undo an earlier grade.
        const { palettePatch, moodPatch } = resolveSceneGrade({ mood: operation.mood, palette: operation.palette, intensity: operation.intensity, neutral: 'reset' })
        return { ...currentScene, layers: currentScene.layers.map(layer => layer.type === 'camera' ? layer : { ...layer, effects: { ...layer.effects, ...palettePatch, ...moodPatch } }) }
      }
      if (operation.op === 'set_relationship') return { ...currentScene, layers: currentScene.layers.map(layer => layer.id !== operation.layerId ? layer : { ...layer, relationship: operation.relationship === 'none' ? undefined : { type: operation.relationship, targetLayerId: operation.targetLayerId!, offsetX: operation.offsetX, offsetY: operation.offsetY, strength: operation.strength, rotationOffset: operation.rotationOffset }, animation: { ...layer.animation, orbit: undefined } }) }
      return currentScene
    }, scene)
  }
  const layers = scene.layers.map(layer => proposal.operations.reduce((current, operation) => {
    if (operation.layerId !== current.id) return current
    if (operation.op === 'set_transform') {
      const transform = { ...current.transform, ...operation.patch }
      const dx = transform.x - current.transform.x; const dy = transform.y - current.transform.y
      return { ...current, transform, animation: { ...current.animation, start: { ...current.animation.start, x: current.animation.start.x + dx, y: current.animation.start.y + dy }, end: { ...current.animation.end, x: current.animation.end.x + dx, y: current.animation.end.y + dy }, keyframes: current.animation.keyframes?.map(frame => ({ ...frame, x: frame.x + dx, y: frame.y + dy })) } }
    }
    if (operation.op === 'set_effects') return { ...current, effects: { ...current.effects, ...operation.patch } }
    if (operation.op === 'set_parallax') return current.type === 'camera' ? current : { ...current, parallax: operation.value }
    if (operation.op === 'set_seam_occluder') {
      if (!current.strip) return current
      const previous = current.strip.seamOccluder
      return { ...current, strip: { ...current.strip, seamOccluder: {
        enabled: operation.enabled,
        kind: operation.kind ?? previous?.kind ?? 'pole',
        ...(operation.scale === undefined ? (previous?.scale === undefined ? {} : { scale: previous.scale }) : { scale: operation.scale }),
        ...(operation.opacity === undefined ? (previous?.opacity === undefined ? {} : { opacity: previous.opacity }) : { opacity: operation.opacity }),
      } } }
    }
    if (operation.op === 'set_orientation') return { ...current, transform: { ...current.transform, ...(operation.rotationX === undefined ? {} : { rotationX: operation.rotationX }), ...(operation.rotationY === undefined ? {} : { rotationY: operation.rotationY }) } }
    if (operation.op === 'set_motion_preset') return motion(current, operation.preset, operation.duration)
    if (operation.op === 'set_rig_clip') return { ...current, animation: { ...current.animation, clip: operation.clip, clipLoop: operation.loop, clipSpeed: operation.speed, clipOffset: 0, clipTrimStart: 0, clipTrimEnd: undefined } }
    if (operation.op === 'set_keyframes') {
      const first = operation.keyframes[0]; const last = operation.keyframes[operation.keyframes.length - 1]
      return { ...current, transform: { ...current.transform, x: last.x, y: last.y, scale: last.scale, opacity: last.opacity, rotation: last.rotation }, animation: { ...current.animation, start: first, end: last, keyframes: operation.keyframes, duration: Math.max(current.animation.duration, last.time), trimEnd: Math.max(current.animation.duration, last.time) } }
    }
    return current
  }, layer))
  return { ...scene, duration: Math.max(scene.duration, ...layers.map(layer => layer.animation.duration)), layers }
}

export const describeSceneCopilotProposal = (scene: Scene, proposal: SceneCopilotProposal) => proposal.operations.map(operation => {
  if (operation.op === 'set_scene_grade') return `Scene grade: ${operation.palette}${operation.mood ? ` / ${operation.mood}` : ''}`
  const label = layerById(scene, operation.layerId).name
  if (operation.op === 'set_transform') return `${label}: ${Object.entries(operation.patch).map(([key, value]) => `${key} → ${value}`).join(', ')}`
  if (operation.op === 'set_effects') return `${label}: ${Object.entries(operation.patch).map(([key, value]) => `${key} → ${value}`).join(', ')}`
  if (operation.op === 'set_seam_occluder') return `${label}: seam cover ${operation.enabled ? `${operation.kind ?? 'kept'}${operation.scale ? ` ×${operation.scale}` : ''}${operation.opacity ? ` / ${Math.round(operation.opacity * 100)}%` : ''}` : 'off'}`
  if (operation.op === 'set_motion_preset') return `${label}: ${operation.preset.replace('_', ' ')} motion`
  if (operation.op === 'set_keyframes') return `${label}: ${operation.keyframes.length} keyframes`
  if (operation.op === 'set_rig_clip') return `${label}: rig clip ${operation.clip}`
  if (operation.op === 'set_camera_motion') return `${label}: ${operation.preset} camera`
  if (operation.op === 'set_relationship') return `${label}: ${operation.relationship === 'none' ? 'relationship removed' : `${operation.relationship} → ${layerById(scene, operation.targetLayerId!).name}`}`
  return `${label}: ${operation.op.replaceAll('_', ' ')}`
})
