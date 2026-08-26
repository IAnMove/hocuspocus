import { memo, useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { AlignHorizontalJustifyCenter, AlignVerticalJustifyCenter, Box, Camera, ChevronDown, ChevronDown as Down, ChevronUp, CloudRain, Copy, CopyPlus, Download, Eye, EyeOff, FileJson, Film, FolderOpen, Grid3X3, Image as ImageIcon, Loader2, Lock, Magnet, Mic, Play, Plus, Redo2, Save, Trash2, Undo2, Unlock, Video } from 'lucide-react'
import { ArrayBufferTarget, Muxer } from 'mp4-muxer'
import { useStore } from '../../stores/useStore'
import { fetchJobStatus, generateLlmText, saveScene as saveSceneOutput, saveSceneRecording, submitGeneration, uploadImage } from '../../api/client'
import { SceneRecipePanel } from './SceneRecipePanel'
import type { SceneRecipe } from '../../lib/sceneRecipe'
import { parseSceneFile, sceneFileName, serializeSceneFile } from '../../lib/sceneFile'
import { SceneLibraryDialog } from './SceneLibraryDialog'
import { PENDING_SCENE_KEY } from '../../lib/sceneOutput'
import { assessNarrativeAsset } from '../../lib/assetSuitability'
import { getSceneClipTime } from '../../lib/sceneClip'
import { sanitizeSceneMotion } from '../../lib/sceneMotion'
import { createNarrativeScene, getNarrativeTemplate, NARRATIVE_SCENE_TEMPLATES, type NarrativeSceneId, type NarrativeTemplateInput } from '../../lib/sceneNarrative'
import { applySceneCopilotProposal, buildSceneCopilotSystemPrompt, buildSceneScopeCopilotSystemPrompt, describeSceneCopilotProposal, parseSceneCopilotProposal, SCENE_COPILOT_JSON_SCHEMA, type SceneCopilotProposal } from '../../lib/sceneCopilot'
import { evaluateSceneLayer, getSceneEvents, getSceneKeyframes, getSceneLayerTiming, mapSceneAnimationPoints, normalizeSceneEvents, normalizeSceneKeyframes, sceneLayerMotionProgress, sceneProgressFromSeconds, sceneTimeToLayerTime, withNormalizedSceneTiming, withSceneKeyframes } from '../../lib/sceneTimeline'
import { normalizeSeamOccluder, paintSeamOccluder, seamOccluderDataUri, type SeamOccluderKind } from '../../lib/seamOccluder'
import type { Scene, SceneAnimationEvent, SceneAtmosphereKind, SceneBlendMode, SceneCurve, SceneFrameRate, SceneKeyframe, SceneLayer, SceneLayerType, SceneMask } from '../../types'
import { SceneTimeline } from './SceneTimeline'
import { CylinderPanoramaComparison } from './CylinderPanoramaComparison'

type Point = { x: number; y: number; scale: number; opacity?: number; rotation?: number }
type AnimatorLayerType = SceneLayerType
type VisualLayerType = Exclude<SceneLayerType, 'camera'>
type ParallaxPreset = 'background' | 'midground' | 'foreground'
type AnimatorLayer = Omit<SceneLayer, 'type' | 'animation'> & {
  type: AnimatorLayerType
  /** Camera-pan response. Distant layers move less; foreground layers move more. */
  parallax?: number
  animation: Omit<SceneLayer['animation'], 'start' | 'end'> & { start: Point; end: Point }
}
type AnimatorScene = Omit<Scene, 'layers'> & { layers: AnimatorLayer[] }
type VisualAnimatorLayer = AnimatorLayer & { type: VisualLayerType }
type LayerState = { x: number; y: number; scale: number; opacity: number; rotation: number; z: number; modelYaw?: number }
type PresetCategory = 'classic' | 'game' | 'cinematic'
type Preset = { id: string; label: string; category: PresetCategory; start: Point; end: Point; duration: number; spin: boolean; curve: SceneCurve; requiresTarget?: boolean; preview: string; poster: string }
type CameraPreset = { id: string; label: string; start: Point; end: Point; duration: number; curve: SceneCurve; shake?: { amount: number; frequency: number; seed?: number } }
type PhotoMotionPreset = CameraPreset & { description: string }
type Gesture = { id: string; mode: 'move' | 'resize' | 'orbit'; startX: number; startY: number; x: number; y: number; scale: number; rotationX: number; rotationY: number }
type LayerEffects = Required<NonNullable<SceneLayer['effects']>>
type LayerStrip = Required<Omit<NonNullable<SceneLayer['strip']>, 'seamOccluder'>> & {
  seamOccluder: { enabled: boolean; kind: SeamOccluderKind; scale: number; opacity: number }
}
type Atmosphere = Required<NonNullable<SceneLayer['atmosphere']>>
type ModelViewerAnimationElement = HTMLElement & { loaded?: boolean; availableAnimations?: string[]; animationName?: string; currentTime: number; duration: number; pause: () => void }
type SpeechRecognizer = { lang: string; continuous: boolean; interimResults: boolean; start: () => void; stop: () => void; onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onerror: (() => void) | null; onend: (() => void) | null }
type SpeechRecognizerConstructor = new () => SpeechRecognizer

const makePoint = (x: number, y: number, scale: number): Point => ({ x, y, scale })
const CAMERA_PRESETS: CameraPreset[] = [
  { id: 'camera-locked', label: 'Locked shot', start: { x: 50, y: 50, scale: 1, rotation: 0 }, end: { x: 50, y: 50, scale: 1, rotation: 0 }, duration: 5, curve: 'linear' },
  { id: 'camera-pan-right', label: 'Pan right', start: { x: 35, y: 50, scale: 1, rotation: 0 }, end: { x: 65, y: 50, scale: 1, rotation: 0 }, duration: 5, curve: 'ease' },
  { id: 'camera-pan-left', label: 'Pan left', start: { x: 65, y: 50, scale: 1, rotation: 0 }, end: { x: 35, y: 50, scale: 1, rotation: 0 }, duration: 5, curve: 'ease' },
  { id: 'camera-push-in', label: 'Slow push-in', start: { x: 50, y: 50, scale: 1, rotation: 0 }, end: { x: 50, y: 50, scale: 1.55, rotation: 0 }, duration: 6, curve: 'ease' },
  { id: 'camera-pull-out', label: 'Reveal pull-out', start: { x: 50, y: 50, scale: 1.6, rotation: 0 }, end: { x: 50, y: 50, scale: 1, rotation: 0 }, duration: 5, curve: 'ease' },
  { id: 'camera-crane-up', label: 'Crane up', start: { x: 50, y: 68, scale: 1.15, rotation: 0 }, end: { x: 50, y: 34, scale: 1, rotation: 0 }, duration: 5, curve: 'ease' },
  { id: 'camera-dutch-drift', label: 'Dutch drift', start: { x: 44, y: 54, scale: 1.05, rotation: -6 }, end: { x: 57, y: 46, scale: 1.28, rotation: 7 }, duration: 6, curve: 'ease' },
  { id: 'camera-handheld', label: 'Handheld · shake', start: { x: 50, y: 50, scale: 1.08, rotation: 0 }, end: { x: 51, y: 49, scale: 1.12, rotation: .6 }, duration: 6, curve: 'ease', shake: { amount: .75, frequency: 3.2, seed: 1.7 } },
  { id: 'camera-whip-pan', label: 'Whip pan · shake', start: { x: 28, y: 50, scale: 1.18, rotation: -2 }, end: { x: 72, y: 50, scale: 1.05, rotation: 2 }, duration: 1.1, curve: 'dramatic', shake: { amount: .35, frequency: 7, seed: 3.1 } },
  { id: 'camera-dolly', label: 'Dolly reveal', start: { x: 36, y: 57, scale: 1.5, rotation: -2 }, end: { x: 58, y: 46, scale: .92, rotation: 0 }, duration: 5.5, curve: 'ease' },
]
const PHOTO_MOTION_PRESETS: PhotoMotionPreset[] = [
  { id: 'photo-documentary-push', label: 'Documentary push-in', description: 'A restrained slow move toward the subject.', start: { x: 50, y: 51, scale: 1.04, rotation: 0 }, end: { x: 48, y: 47, scale: 1.3, rotation: 0 }, duration: 7, curve: 'ease' },
  { id: 'photo-ken-burns-left', label: 'Ken Burns · left', description: 'Classic archival pan from right to left.', start: { x: 43, y: 50, scale: 1.18, rotation: 0 }, end: { x: 57, y: 50, scale: 1.24, rotation: 0 }, duration: 8, curve: 'ease' },
  { id: 'photo-ken-burns-right', label: 'Ken Burns · right', description: 'Classic archival pan from left to right.', start: { x: 57, y: 50, scale: 1.18, rotation: 0 }, end: { x: 43, y: 50, scale: 1.24, rotation: 0 }, duration: 8, curve: 'ease' },
  { id: 'photo-portrait-rise', label: 'Portrait rise', description: 'Starts low and slowly discovers the face.', start: { x: 50, y: 58, scale: 1.12, rotation: 0 }, end: { x: 50, y: 42, scale: 1.3, rotation: 0 }, duration: 7, curve: 'ease' },
  { id: 'photo-reveal-pullback', label: 'Reveal pull-back', description: 'Opens from a detail into the full photograph.', start: { x: 52, y: 48, scale: 1.42, rotation: 0 }, end: { x: 50, y: 50, scale: 1.06, rotation: 0 }, duration: 7, curve: 'ease' },
  { id: 'photo-diagonal-discovery', label: 'Diagonal discovery', description: 'Elegant diagonal travel for landscapes and art.', start: { x: 42, y: 58, scale: 1.08, rotation: 0 }, end: { x: 58, y: 42, scale: 1.32, rotation: 0 }, duration: 7.5, curve: 'ease' },
  { id: 'photo-intimate-closeup', label: 'Intimate close-up', description: 'A gentle asymmetric move for emotional beats.', start: { x: 51, y: 53, scale: 1.1, rotation: 0 }, end: { x: 46, y: 45, scale: 1.43, rotation: 0 }, duration: 8, curve: 'ease' },
  { id: 'photo-dutch-tension', label: 'Dutch tension', description: 'Slow roll and push for mystery or conflict.', start: { x: 47, y: 53, scale: 1.12, rotation: -2.5 }, end: { x: 54, y: 47, scale: 1.34, rotation: 3 }, duration: 6.5, curve: 'ease' },
  { id: 'photo-handheld-memory', label: 'Memory drift', description: 'Subtle smooth drift for memories and reportage.', start: { x: 50, y: 51, scale: 1.12, rotation: -.3 }, end: { x: 49, y: 48, scale: 1.22, rotation: .4 }, duration: 7, curve: 'ease' },
  { id: 'photo-rostrum-scan', label: 'Rostrum scan', description: 'A measured top-to-bottom move for documents and maps.', start: { x: 50, y: 40, scale: 1.26, rotation: 0 }, end: { x: 50, y: 60, scale: 1.26, rotation: 0 }, duration: 8, curve: 'ease' },
]
const PRESETS: Preset[] = ([
  ['turntable', 'Product turntable', 50, 50, 50, 50, .8, .8, 5, true, 'linear'], ['meteor', 'Meteor fly-by', -10, 82, 112, 18, .22, .65, 2, true, 'dramatic'], ['space-cruise', 'Spacecraft cruise', 8, 54, 92, 43, .48, .68, 5, true, 'ease'], ['hover', 'Hovering reveal', 50, 54, 50, 46, .7, .76, 4, true, 'ease'], ['landing', 'Landing', 50, -12, 50, 60, .2, .82, 4, false, 'bounce'], ['liftoff', 'Lift-off', 50, 68, 54, -15, .82, .28, 3, false, 'dramatic'], ['zoom-in', 'Hero zoom in', 50, 50, 50, 50, .18, 1.35, 3, true, 'dramatic'], ['zoom-out', 'Retreat into distance', 50, 50, 50, 50, 1.25, .18, 3, true, 'ease'], ['drift-right', 'Slow drift right', 25, 50, 75, 50, .68, .68, 6, false, 'linear'], ['drift-left', 'Slow drift left', 75, 50, 25, 50, .68, .68, 6, false, 'linear'], ['diagonal-rise', 'Diagonal rise', 20, 82, 78, 22, .38, .82, 4, true, 'ease'], ['diagonal-drop', 'Diagonal drop', 78, 16, 24, 84, .82, .35, 3, true, 'dramatic'], ['pop', 'Pop into frame', 50, 50, 50, 50, .05, .85, 1, true, 'bounce'], ['glide', 'Low glide', -8, 72, 108, 70, .4, .52, 4, false, 'ease'], ['pass-camera', 'Pass the camera', 16, 50, 90, 50, .18, 1.5, 3, true, 'dramatic'], ['vibrate', 'Nave vibrando', 49, 51, 51, 49, .72, .75, 2, false, 'bounce'], ['orbit-sweep', 'Orbit sweep', 18, 70, 86, 30, .32, .9, 5, true, 'ease'], ['center-reveal', 'Center reveal', 50, 105, 50, 52, .35, .9, 3, true, 'ease'], ['exit-frame', 'Emergency exit', 50, 50, 120, -10, .8, .25, 2, true, 'dramatic'], ['floating-logo', 'Floating logo', 50, 45, 50, 55, .72, .72, 4, true, 'ease'],
].map(([id, label, sx, sy, ex, ey, ss, es, duration, spin, curve]) => ({ id: id as string, label: label as string, category: 'classic' as const, start: makePoint(sx as number, sy as number, ss as number), end: makePoint(ex as number, ey as number, es as number), duration: duration as number, spin: spin as boolean, curve: curve as SceneCurve })) as Array<Omit<Preset, 'preview' | 'poster'>>).concat([
  { id: 'orbit-layer', label: 'Orbit around another layer', category: 'cinematic', start: makePoint(50, 50, .45), end: makePoint(50, 50, .45), duration: 5, spin: true, curve: 'linear', requiresTarget: true },
  { id: 'game-spawn', label: 'Game spawn', category: 'game', start: { x: 50, y: 55, scale: .05, opacity: 0 }, end: { x: 50, y: 50, scale: .8, opacity: 1 }, duration: 1.2, spin: true, curve: 'bounce' },
  { id: 'loot-drop', label: 'Loot drop', category: 'game', start: makePoint(50, -18, .35), end: makePoint(50, 72, .72), duration: 1.4, spin: true, curve: 'bounce' },
  { id: 'item-pickup', label: 'Item pickup', category: 'game', start: { x: 50, y: 68, scale: .72, opacity: 1 }, end: { x: 50, y: 20, scale: .12, opacity: 0 }, duration: .9, spin: true, curve: 'dramatic' },
  { id: 'projectile-launch', label: 'Projectile launch', category: 'game', start: makePoint(-12, 58, .16), end: makePoint(115, 42, .5), duration: .75, spin: true, curve: 'dramatic' },
  { id: 'boss-entrance', label: 'Boss entrance', category: 'game', start: { x: 50, y: -20, scale: .18, opacity: 0 }, end: { x: 50, y: 58, scale: 1.25, opacity: 1 }, duration: 2.2, spin: false, curve: 'bounce' },
  { id: 'dodge-dash', label: 'Dodge dash', category: 'game', start: makePoint(30, 55, .82), end: makePoint(78, 50, .68), duration: .55, spin: false, curve: 'dramatic' },
  { id: 'hit-knockback', label: 'Hit knockback', category: 'game', start: makePoint(55, 48, .88), end: makePoint(32, 58, .62), duration: .65, spin: true, curve: 'bounce' },
  { id: 'power-up-rise', label: 'Power-up rise', category: 'game', start: { x: 50, y: 78, scale: .3, opacity: .25 }, end: { x: 50, y: 42, scale: 1.05, opacity: 1 }, duration: 1.8, spin: true, curve: 'bounce' },
  { id: 'cinematic-push', label: 'Cinematic push-in', category: 'cinematic', start: makePoint(38, 55, .28), end: makePoint(54, 48, 1.18), duration: 5.5, spin: false, curve: 'ease' },
  { id: 'hero-flyover', label: 'Hero flyover', category: 'cinematic', start: makePoint(-18, 22, .22), end: makePoint(118, 72, 1.15), duration: 4.2, spin: true, curve: 'ease' },
  { id: 'fade-reveal', label: 'Fade reveal', category: 'cinematic', start: { x: 50, y: 50, scale: .78, opacity: 0 }, end: { x: 50, y: 50, scale: .92, opacity: 1 }, duration: 2.5, spin: false, curve: 'ease' },
  { id: 'foreground-parallax', label: 'Foreground parallax', category: 'cinematic', start: makePoint(-28, 50, 1.55), end: makePoint(128, 50, 1.55), duration: 7, spin: false, curve: 'linear' },
  { id: 'crane-reveal', label: 'Crane reveal', category: 'cinematic', start: { x: 50, y: 112, scale: 1.3, opacity: .2 }, end: { x: 50, y: 45, scale: .72, opacity: 1 }, duration: 4.5, spin: false, curve: 'ease' },
  { id: 'portal-arrival', label: 'Portal arrival', category: 'cinematic', start: { x: 50, y: 50, scale: .02, opacity: 0 }, end: { x: 50, y: 50, scale: 1, opacity: 1 }, duration: 1.6, spin: true, curve: 'dramatic' },
]).map(preset => ({ ...preset, preview: `/preset-previews/${preset.id}.webm`, poster: `/preset-previews/${preset.id}.webp` }))

const DEFAULT_COMPOSITION: NonNullable<Scene['composition']> = { showGrid: false, gridSize: 10, snap: false, safeArea: 'none' }
const DEFAULT_EFFECTS: LayerEffects = { blur: 0, brightness: 1, contrast: 1, saturation: 1, hue: 0, glow: 0, shadow: 0, blendMode: 'normal', mask: 'none', maskRadius: 12 }
const DEFAULT_STRIP: LayerStrip = { enabled: false, count: 5, spacing: 24, direction: 'down', speed: 18, phase: 0, seamOccluder: { enabled: false, kind: 'pole', scale: 1, opacity: .82 } }
const ATMOSPHERE_KINDS: SceneAtmosphereKind[] = ['rain', 'snow', 'dust', 'embers', 'fog', 'smoke', 'ash', 'fireflies', 'confetti', 'bokeh', 'sparkles', 'bubbles', 'speedlines', 'leaves']
const ATMOSPHERE_LABELS: Record<SceneAtmosphereKind, string> = {
  rain: 'Cinematic rain',
  snow: 'Falling snow',
  dust: 'Floating dust',
  embers: 'Rising embers',
  fog: 'Rolling fog',
  smoke: 'Drifting smoke',
  ash: 'Falling ash',
  fireflies: 'Fireflies',
  confetti: 'Confetti shower',
  bokeh: 'Dreamy bokeh',
  sparkles: 'Magic sparkles',
  bubbles: 'Underwater bubbles',
  speedlines: 'Speed lines',
  leaves: 'Falling leaves',
}
const ATMOSPHERE_DESCRIPTIONS: Record<SceneAtmosphereKind, string> = {
  rain: 'Layered rain streaks with depth and wind.',
  snow: 'Soft flakes with gentle lateral drift.',
  dust: 'Warm motes for interiors, ruins and sunbeams.',
  embers: 'Glowing particles rising from fire or destruction.',
  fog: 'Large translucent banks moving across the frame.',
  smoke: 'Soft plumes that rise and disperse with the wind.',
  ash: 'Irregular grey fallout for burned or volcanic scenes.',
  fireflies: 'Warm wandering lights with organic pulsing.',
  confetti: 'Multicolour rotating pieces for celebrations.',
  bokeh: 'Large dreamy lights with a slow cinematic drift.',
  sparkles: 'Twinkling four-point stars for magical reveals.',
  bubbles: 'Outlined bubbles rising through underwater shots.',
  speedlines: 'Fast directional streaks for action and impacts.',
  leaves: 'Rotating autumn leaves with varied warm colours.',
}
const ATMOSPHERE_OPACITY: Record<SceneAtmosphereKind, number> = {
  rain: .92, snow: .95, dust: .78, embers: .92, fog: .58, smoke: .62, ash: .72,
  fireflies: .95, confetti: 1, bokeh: .58, sparkles: .9, bubbles: .85, speedlines: .7, leaves: .95,
}
const ATMOSPHERE_PRESETS: Record<SceneAtmosphereKind, Atmosphere> = {
  rain: { kind: 'rain', density: 145, speed: 1.3, size: 1.65, wind: -10, color: '#dbeafe' },
  snow: { kind: 'snow', density: 90, speed: .42, size: 2.15, wind: 8, color: '#ffffff' },
  dust: { kind: 'dust', density: 58, speed: .25, size: 2.5, wind: 18, color: '#fde68a' },
  embers: { kind: 'embers', density: 68, speed: .62, size: 1.55, wind: 10, color: '#fb923c' },
  fog: { kind: 'fog', density: 16, speed: .18, size: 1.15, wind: 28, color: '#dbeafe' },
  smoke: { kind: 'smoke', density: 22, speed: .3, size: .85, wind: 12, color: '#cbd5e1' },
  ash: { kind: 'ash', density: 95, speed: .34, size: 1.35, wind: 14, color: '#d1d5db' },
  fireflies: { kind: 'fireflies', density: 38, speed: .22, size: 1.4, wind: 4, color: '#fde047' },
  confetti: { kind: 'confetti', density: 86, speed: .72, size: 1.65, wind: 12, color: '#f472b6' },
  bokeh: { kind: 'bokeh', density: 24, speed: .12, size: 2.8, wind: 6, color: '#f0abfc' },
  sparkles: { kind: 'sparkles', density: 42, speed: .18, size: 1.8, wind: 4, color: '#ffffff' },
  bubbles: { kind: 'bubbles', density: 46, speed: .45, size: 1.6, wind: 5, color: '#bae6fd' },
  speedlines: { kind: 'speedlines', density: 72, speed: 1.65, size: 1.15, wind: 45, color: '#e0f2fe' },
  leaves: { kind: 'leaves', density: 54, speed: .48, size: 1.8, wind: 20, color: '#f59e0b' },
}
const blankScene = (): AnimatorScene => ({ version: 1, name: 'Untitled scene', width: 1280, height: 720, fps: 30, duration: 5, layers: [], composition: { ...DEFAULT_COMPOSITION } })
const AUTOSAVE_KEY = 'maestro-scene-animator-autosave-v1'
const HISTORY_LIMIT = 80
const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
const finiteNumber = (value: unknown, fallback: number) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
const boundedNumber = (value: unknown, fallback: number, min: number, max: number) => Math.max(min, Math.min(max, finiteNumber(value, fallback)))
const normalizedEffects = (value: SceneLayer['effects'] | undefined): LayerEffects => ({
  blur: boundedNumber(value?.blur, DEFAULT_EFFECTS.blur, 0, 3),
  brightness: boundedNumber(value?.brightness, DEFAULT_EFFECTS.brightness, 0, 3),
  contrast: boundedNumber(value?.contrast, DEFAULT_EFFECTS.contrast, 0, 3),
  saturation: boundedNumber(value?.saturation, DEFAULT_EFFECTS.saturation, 0, 4),
  hue: boundedNumber(value?.hue, DEFAULT_EFFECTS.hue, -180, 180),
  glow: boundedNumber(value?.glow, DEFAULT_EFFECTS.glow, 0, 5),
  shadow: boundedNumber(value?.shadow, DEFAULT_EFFECTS.shadow, 0, 8),
  blendMode: ['normal', 'multiply', 'screen', 'overlay', 'lighten', 'darken'].includes(value?.blendMode ?? '') ? value?.blendMode as SceneBlendMode : 'normal',
  mask: ['none', 'rounded', 'ellipse'].includes(value?.mask ?? '') ? value?.mask as SceneMask : 'none',
  maskRadius: boundedNumber(value?.maskRadius, DEFAULT_EFFECTS.maskRadius, 0, 50),
})
const normalizedStrip = (value: SceneLayer['strip'] | undefined): LayerStrip => ({
  enabled: value?.enabled === true,
  count: Math.round(boundedNumber(value?.count, DEFAULT_STRIP.count, 1, 12)),
  spacing: boundedNumber(value?.spacing, DEFAULT_STRIP.spacing, 2, 200),
  direction: ['up', 'down', 'left', 'right'].includes(value?.direction ?? '') ? value?.direction as LayerStrip['direction'] : DEFAULT_STRIP.direction,
  speed: boundedNumber(value?.speed, DEFAULT_STRIP.speed, 0, 300),
  phase: boundedNumber(value?.phase, DEFAULT_STRIP.phase, -1000, 1000),
  seamOccluder: normalizeSeamOccluder(value?.seamOccluder),
})
const normalizedAtmosphere = (value: SceneLayer['atmosphere'] | undefined): Atmosphere => {
  const kind = ATMOSPHERE_KINDS.includes(value?.kind as SceneAtmosphereKind) ? value!.kind : 'rain'
  const preset = ATMOSPHERE_PRESETS[kind]
  return {
    kind,
    density: Math.round(boundedNumber(value?.density, preset.density, 5, 240)),
    speed: boundedNumber(value?.speed, preset.speed, .05, 4),
    size: boundedNumber(value?.size, preset.size, .2, 8),
    wind: boundedNumber(value?.wind, preset.wind, -100, 100),
    color: typeof value?.color === 'string' && /^#[0-9a-f]{6}$/i.test(value.color) ? value.color : preset.color,
  }
}
const particleNoise = (index: number, salt: number) => {
  const value = Math.sin((index + 1) * 12.9898 + salt * 78.233) * 43758.5453
  return value - Math.floor(value)
}
const atmosphereParticles = (atmosphere: Atmosphere, seconds: number) => Array.from({ length: atmosphere.density }, (_, index) => {
  const phase = particleNoise(index, 1.7)
  const baseX = particleNoise(index, 4.1) * 120 - 10
  const baseY = particleNoise(index, 8.3) * 120 - 10
  const depth = .35 + particleNoise(index, 11.9) * .65
  const pulse = .35 + .65 * Math.abs(Math.sin(seconds * (1.2 + depth * 2.4) + phase * Math.PI * 2))
  const rotation = (particleNoise(index, 15.3) * 360 + seconds * atmosphere.speed * (30 + depth * 100)) % 360
  const rate = atmosphere.kind === 'rain' ? .55
    : atmosphere.kind === 'snow' ? .09
      : atmosphere.kind === 'embers' || atmosphere.kind === 'bubbles' ? .16
        : atmosphere.kind === 'confetti' || atmosphere.kind === 'leaves' ? .12
          : atmosphere.kind === 'ash' ? .075
            : atmosphere.kind === 'speedlines' ? .5
              : .045
  const travel = ((phase + seconds * atmosphere.speed * rate * depth) % 1 + 1) % 1
  const wind = atmosphere.wind * travel * .18
  const shared = { size: atmosphere.size * depth, pulse, rotation, variant: Math.floor(particleNoise(index, 19.7) * 6) }
  if (atmosphere.kind === 'embers' || atmosphere.kind === 'smoke' || atmosphere.kind === 'bubbles') return { ...shared, x: baseX + wind + Math.sin(seconds * 1.7 + index) * (atmosphere.kind === 'smoke' ? 4 : 1.8), y: 110 - travel * 120, alpha: atmosphere.kind === 'smoke' ? .12 + depth * .22 : .3 + depth * .65 }
  if (atmosphere.kind === 'dust' || atmosphere.kind === 'fog') return { ...shared, x: ((baseX + travel * (18 + atmosphere.wind) + 10) % 120 + 120) % 120 - 10, y: baseY + Math.sin(seconds * atmosphere.speed + index * 2.1) * (atmosphere.kind === 'fog' ? 5 : 3), alpha: atmosphere.kind === 'fog' ? .1 + depth * .16 : .14 + depth * .32 }
  if (atmosphere.kind === 'fireflies' || atmosphere.kind === 'bokeh' || atmosphere.kind === 'sparkles') return { ...shared, x: baseX + Math.sin(seconds * atmosphere.speed * 2 + index) * (2 + atmosphere.wind * .05), y: baseY + Math.cos(seconds * atmosphere.speed * 1.7 + index * 1.8) * 3, alpha: pulse * (atmosphere.kind === 'bokeh' ? .28 : .85) }
  if (atmosphere.kind === 'speedlines') return { ...shared, x: -10 + travel * 120, y: baseY, alpha: .18 + depth * .58 }
  return { ...shared, x: baseX + wind + (atmosphere.kind === 'snow' || atmosphere.kind === 'ash' || atmosphere.kind === 'leaves' ? Math.sin(seconds * 1.2 + index) * 2.8 : 0), y: -10 + travel * 120, alpha: atmosphere.kind === 'rain' ? .28 + depth * .55 : atmosphere.kind === 'ash' ? .18 + depth * .45 : .35 + depth * .65 }
})
const drawAtmosphere = (context: CanvasRenderingContext2D, atmosphere: Atmosphere, seconds: number, width: number, height: number) => {
  const shortSide = Math.min(width, height)
  const confettiPalette = ['#f472b6', '#60a5fa', '#facc15', '#34d399', '#c084fc', '#fb7185']
  const leafPalette = ['#f59e0b', '#dc2626', '#84cc16', '#d97706', '#a16207', '#fbbf24']
  for (const particle of atmosphereParticles(atmosphere, seconds)) {
    const x = -width / 2 + width * particle.x / 100
    const y = -height / 2 + height * particle.y / 100
    const color = atmosphere.kind === 'confetti' ? confettiPalette[particle.variant] : atmosphere.kind === 'leaves' ? leafPalette[particle.variant] : atmosphere.color
    context.save()
    context.globalAlpha *= particle.alpha
    context.fillStyle = color
    context.strokeStyle = color
    context.lineCap = 'round'
    if (atmosphere.kind === 'rain') {
      context.lineWidth = Math.max(1, shortSide * particle.size / 520)
      context.beginPath(); context.moveTo(x, y); context.lineTo(x + atmosphere.wind * width / 1900, y + height * particle.size / 30); context.stroke()
    } else if (atmosphere.kind === 'fog' || atmosphere.kind === 'smoke') {
      const radius = shortSide * particle.size / (atmosphere.kind === 'fog' ? 8 : 11)
      const gradient = context.createRadialGradient(x, y, 0, x, y, radius)
      gradient.addColorStop(0, color)
      gradient.addColorStop(.45, `${color}88`)
      gradient.addColorStop(1, `${color}00`)
      context.fillStyle = gradient
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.fill()
    } else if (atmosphere.kind === 'fireflies' || atmosphere.kind === 'embers') {
      const radius = Math.max(1, shortSide * particle.size / 420)
      context.shadowColor = color; context.shadowBlur = radius * (atmosphere.kind === 'fireflies' ? 7 : 4)
      context.globalAlpha *= atmosphere.kind === 'fireflies' ? particle.pulse : 1
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.fill()
    } else if (atmosphere.kind === 'confetti') {
      const unit = shortSide * particle.size / 270
      context.translate(x, y); context.rotate(particle.rotation * Math.PI / 180)
      context.fillRect(-unit / 2, -unit * 1.4, unit, unit * 2.8)
    } else if (atmosphere.kind === 'bokeh') {
      const radius = shortSide * particle.size / 42
      context.lineWidth = Math.max(1, radius * .08)
      context.globalAlpha *= particle.pulse
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.fill()
      context.globalAlpha *= .8; context.strokeStyle = '#ffffff'; context.stroke()
    } else if (atmosphere.kind === 'sparkles') {
      const radius = shortSide * particle.size * particle.pulse / 135
      context.shadowColor = color; context.shadowBlur = radius * 2
      context.lineWidth = Math.max(1, radius * .14)
      context.beginPath(); context.moveTo(x - radius, y); context.lineTo(x + radius, y); context.moveTo(x, y - radius); context.lineTo(x, y + radius); context.stroke()
    } else if (atmosphere.kind === 'bubbles') {
      const radius = shortSide * particle.size / 145
      context.lineWidth = Math.max(1, radius * .16)
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.stroke()
      context.globalAlpha *= .65; context.fillStyle = '#ffffff'; context.beginPath(); context.arc(x - radius * .32, y - radius * .3, radius * .16, 0, Math.PI * 2); context.fill()
    } else if (atmosphere.kind === 'speedlines') {
      const length = width * particle.size / 9
      context.lineWidth = Math.max(1, shortSide * particle.size / 480)
      context.beginPath(); context.moveTo(x - length, y - atmosphere.wind * height / 3500); context.lineTo(x, y); context.stroke()
    } else if (atmosphere.kind === 'leaves') {
      const radius = shortSide * particle.size / 180
      context.translate(x, y); context.rotate(particle.rotation * Math.PI / 180)
      context.beginPath(); context.ellipse(0, 0, radius, radius * .48, 0, 0, Math.PI * 2); context.fill()
      context.strokeStyle = '#78350f'; context.lineWidth = Math.max(.5, radius * .08); context.beginPath(); context.moveTo(-radius, 0); context.lineTo(radius, 0); context.stroke()
    } else {
      const radius = Math.max(.8, shortSide * particle.size / (atmosphere.kind === 'dust' ? 330 : atmosphere.kind === 'ash' ? 520 : 470))
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.fill()
    }
    context.restore()
  }
}
const stripOffsets = (layer: AnimatorLayer, sceneSeconds: number) => {
  const strip = normalizedStrip(layer.strip)
  if (!strip.enabled || strip.count <= 1) return [{ x: 0, y: 0 }]
  const period = strip.count * strip.spacing
  const sign = strip.direction === 'up' || strip.direction === 'left' ? -1 : 1
  const travel = sign * (strip.phase + sceneSeconds * strip.speed)
  const wrap = (value: number) => ((value + period / 2) % period + period) % period - period / 2
  return Array.from({ length: strip.count }, (_, index) => {
    const offset = wrap((index - (strip.count - 1) / 2) * strip.spacing + travel)
    return strip.direction === 'up' || strip.direction === 'down' ? { x: 0, y: offset } : { x: offset, y: 0 }
  })
}
const effectFilter = (effects: LayerEffects, pixelUnit: number) => {
  const filters = [`brightness(${effects.brightness})`, `contrast(${effects.contrast})`, `saturate(${effects.saturation})`, `hue-rotate(${effects.hue}deg)`]
  if (effects.blur > 0) filters.unshift(`blur(${(effects.blur * pixelUnit).toFixed(2)}px)`)
  if (effects.glow > 0) filters.push(`drop-shadow(0 0 ${(effects.glow * pixelUnit).toFixed(2)}px rgba(96,165,250,.9))`)
  if (effects.shadow > 0) filters.push(`drop-shadow(0 ${(effects.shadow * pixelUnit * .35).toFixed(2)}px ${(effects.shadow * pixelUnit * .7).toFixed(2)}px rgba(0,0,0,.8))`)
  return filters.join(' ')
}
const hasCanvasFilterEffects = (effects: LayerEffects) => effects.blur > 0 || effects.glow > 0 || effects.shadow > 0 || effects.brightness !== 1 || effects.contrast !== 1 || effects.saturation !== 1 || effects.hue !== 0
const applyLayerMask = (context: CanvasRenderingContext2D, effects: LayerEffects, width: number, height: number) => {
  context.beginPath()
  if (effects.mask === 'none') context.rect(-width / 2, -height / 2, width, height)
  else if (effects.mask === 'ellipse') context.ellipse(0, 0, width / 2, height / 2, 0, 0, Math.PI * 2)
  else {
    const x = -width / 2; const y = -height / 2; const radius = Math.min(width, height) * effects.maskRadius / 100
    context.moveTo(x + radius, y); context.lineTo(x + width - radius, y); context.arcTo(x + width, y, x + width, y + radius, radius)
    context.lineTo(x + width, y + height - radius); context.arcTo(x + width, y + height, x + width - radius, y + height, radius)
    context.lineTo(x + radius, y + height); context.arcTo(x, y + height, x, y + height - radius, radius)
    context.lineTo(x, y + radius); context.arcTo(x, y, x + radius, y, radius)
  }
  context.closePath(); context.clip()
}
const isMissing = (source: string) => source.startsWith('blob:')
const isAnimatorLayerType = (value: unknown): value is AnimatorLayerType => value === 'model3d' || value === 'image' || value === 'video' || value === 'overlay' || value === 'effect' || value === 'camera'
const isVisualLayer = (layer: AnimatorLayer): layer is VisualAnimatorLayer => layer.type !== 'camera'
const findLayerElements = (root: HTMLElement | null, id: string) => Array.from(root?.querySelectorAll<HTMLElement>('[data-layer-id]') ?? []).filter(element => element.dataset.layerId === id)
const findLayerElement = (root: HTMLElement | null, id: string) => findLayerElements(root, id)[0] ?? null
const modelViewerCanvas = (element: HTMLElement | null) => {
  const root = element?.shadowRoot
  if (!root) return null
  const rendered = root.querySelector<HTMLCanvasElement>('#webgl-canvas')
  if (rendered) return rendered
  const canvases = Array.from(root.querySelectorAll<HTMLCanvasElement>('canvas'))
  return canvases.find(canvas => canvas.getBoundingClientRect().width > 0) ?? canvases.at(-1) ?? null
}
const iconFor = (type: AnimatorLayerType) => type === 'camera' ? <Camera size={13} /> : type === 'effect' ? <CloudRain size={13} /> : type === 'model3d' ? <Box size={13} /> : type === 'video' ? <Video size={13} /> : <ImageIcon size={13} />
const PARALLAX_PRESETS: Record<ParallaxPreset, number> = { background: .3, midground: .7, foreground: 1.2 }
const RESOLUTIONS = [
  ['HD landscape', 1280, 720], ['Full HD landscape', 1920, 1080], ['4K landscape', 3840, 2160],
  ['Square', 1080, 1080], ['HD portrait', 720, 1280], ['Full HD portrait', 1080, 1920], ['4K portrait', 2160, 3840],
] as const

const assignZ = (layers: AnimatorLayer[]) => layers.map((layer, index) => ({ ...layer, z: index * 10 }))
const normalizeZ = (layers: AnimatorLayer[]) => assignZ([...layers].sort((a, b) => a.z - b.z))
const dependencyTargets = (layer: AnimatorLayer) => [layer.relationship?.targetLayerId, layer.animation.orbit?.targetLayerId].filter((id): id is string => Boolean(id))
const dependencyWouldCycleIn = (layers: AnimatorLayer[], layerId: string, targetId: string) => {
  const pending = [targetId]
  const visited = new Set<string>()
  while (pending.length > 0) {
    const currentId = pending.pop()
    if (!currentId) continue
    if (currentId === layerId) return true
    if (visited.has(currentId)) continue
    visited.add(currentId)
    const current = layers.find(layer => layer.id === currentId)
    if (current) pending.push(...dependencyTargets(current))
  }
  return false
}
const breakDependencyCycles = (layers: AnimatorLayer[]) => {
  let next = layers
  for (const candidate of layers) {
    const current = next.find(layer => layer.id === candidate.id)
    if (!current) continue
    if (current.relationship && dependencyWouldCycleIn(next, current.id, current.relationship.targetLayerId)) {
      next = next.map(layer => layer.id === current.id ? { ...layer, relationship: undefined } : layer)
    }
    const withRelationshipChecked = next.find(layer => layer.id === candidate.id)
    if (withRelationshipChecked?.animation.orbit && dependencyWouldCycleIn(next, withRelationshipChecked.id, withRelationshipChecked.animation.orbit.targetLayerId)) {
      next = next.map(layer => layer.id === withRelationshipChecked.id ? { ...layer, animation: { ...layer.animation, orbit: undefined } } : layer)
    }
  }
  return next
}
const ANIMATED_FIELDS = ['x', 'y', 'scale', 'opacity', 'rotation'] as const
type AnimatedField = typeof ANIMATED_FIELDS[number]

const endpointValue = (layer: AnimatorLayer, endpoint: 'start' | 'end', field: AnimatedField) => {
  const value = layer.animation[endpoint][field]
  if (typeof value === 'number') return value
  return field === 'opacity' ? layer.transform.opacity : field === 'rotation' ? layer.transform.rotation ?? 0 : 0
}

const reconcileLegacyKeyframeUpdate = (before: AnimatorLayer, after: AnimatorLayer): AnimatorLayer => {
  if (!before.animation.keyframes?.length || after.animation.keyframes !== before.animation.keyframes) return after
  let frames = getSceneKeyframes(before)
  for (const field of ANIMATED_FIELDS) {
    const beforeStart = endpointValue(before, 'start', field)
    const beforeEnd = endpointValue(before, 'end', field)
    const afterStart = endpointValue(after, 'start', field)
    const afterEnd = endpointValue(after, 'end', field)
    const startChanged = Math.abs(afterStart - beforeStart) > 1e-9
    const endChanged = Math.abs(afterEnd - beforeEnd) > 1e-9
    if (!startChanged && !endChanged) continue
    const transformChanged = field in before.transform && field in after.transform && before.transform[field as keyof typeof before.transform] !== after.transform[field as keyof typeof after.transform]
    if (startChanged && endChanged && transformChanged && (field === 'scale' || field === 'opacity') && Math.abs(afterStart - afterEnd) < 1e-9) {
      frames = frames.map(frame => ({ ...frame, [field]: afterStart }))
    } else if (startChanged && endChanged && Math.abs((afterStart - beforeStart) - (afterEnd - beforeEnd)) < 1e-9) {
      const delta = afterStart - beforeStart
      frames = frames.map(frame => ({ ...frame, [field]: frame[field] + delta }))
    } else {
      frames = frames.map((frame, index) => index === 0 && startChanged ? { ...frame, [field]: afterStart } : index === frames.length - 1 && endChanged ? { ...frame, [field]: afterEnd } : frame)
    }
  }
  if (before.animation.curve !== after.animation.curve) frames = frames.map(frame => ({ ...frame, curve: after.animation.curve }))
  return withSceneKeyframes(after, frames, after.animation.duration) as AnimatorLayer
}

const MotionPresetCard = memo(function MotionPresetCard({ preset, selected, onSelect }: { preset: Preset; scopeId: string; selected: boolean; onSelect: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [hovered, setHovered] = useState(false)
  const play = () => { setHovered(true); const video = videoRef.current; if (!video) return; video.currentTime = 0; void video.play().catch(() => {}) }
  const stop = () => { setHovered(false); const video = videoRef.current; if (!video) return; video.pause(); video.currentTime = 0 }
  return <button type="button" onClick={onSelect} onPointerEnter={play} onPointerLeave={stop} onFocus={play} onBlur={stop} className={`overflow-hidden rounded border text-left transition-colors ${selected ? 'border-accent-blue bg-accent-blue/10 ring-1 ring-accent-blue/40' : 'border-border bg-bg-primary hover:border-accent-blue/70'}`}>
    <div className="relative aspect-video overflow-hidden bg-[#07111f]"><img src={preset.poster} alt="" className="absolute inset-0 h-full w-full object-cover" /><video ref={videoRef} src={preset.preview} poster={preset.poster} muted loop playsInline preload="metadata" className={`pointer-events-none absolute inset-0 h-full w-full object-cover transition-opacity ${hovered ? 'opacity-100' : 'opacity-0'}`} /></div>
    <div className="flex min-h-9 items-center justify-between gap-1 px-1.5 py-1"><span className="line-clamp-2 text-[9px] leading-tight text-text-secondary">{preset.label}</span><span className="flex shrink-0 flex-col items-end gap-0.5">{preset.category !== 'classic' && <span className={`rounded px-1 py-0.5 text-[7px] uppercase ${preset.category === 'game' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-purple-500/15 text-purple-300'}`}>{preset.category}</span>}{preset.requiresTarget && <span className="rounded bg-accent-blue/15 px-1 py-0.5 text-[8px] text-accent-blue">2 layers</span>}</span></div>
  </button>
}, (previous, next) => previous.preset === next.preset && previous.scopeId === next.scopeId && previous.selected === next.selected)

const PhotoMotionPresetCard = memo(function PhotoMotionPresetCard({ preset, source, selected, onSelect }: { preset: PhotoMotionPreset; source: string; scopeId: string; selected: boolean; onSelect: () => void }) {
  const [hovered, setHovered] = useState(false)
  const camera = hovered ? preset.end : preset.start
  const previewTransform = `translate(${(50 - camera.x) * .55}%, ${(50 - camera.y) * .55}%) scale(${camera.scale}) rotate(${-Number(camera.rotation ?? 0)}deg)`
  return <button
    type="button"
    title={preset.description}
    onClick={onSelect}
    onPointerEnter={() => setHovered(true)}
    onPointerLeave={() => setHovered(false)}
    onFocus={() => setHovered(true)}
    onBlur={() => setHovered(false)}
    className={`overflow-hidden rounded border text-left transition-colors ${selected ? 'border-cyan-300 bg-cyan-400/10 ring-1 ring-cyan-300/40' : 'border-border bg-bg-primary hover:border-cyan-400/70'}`}
  >
    <div className="relative aspect-video overflow-hidden bg-[#07111f]">
      <img
        src={source}
        alt=""
        className="absolute inset-[-8%] h-[116%] w-[116%] object-cover"
        style={{ transform: previewTransform, transition: hovered ? `transform ${Math.min(3.5, preset.duration * .5)}s ease-in-out` : 'transform 220ms ease-out' }}
      />
      {preset.shake && <span className="absolute right-1 top-1 rounded bg-black/55 px-1 py-0.5 text-[7px] text-cyan-100">organic</span>}
    </div>
    <div className="px-1.5 py-1">
      <div className="text-[9px] leading-tight text-text-secondary">{preset.label}</div>
      <div className="mt-0.5 line-clamp-2 text-[7px] leading-tight text-text-muted">{preset.description}</div>
    </div>
  </button>
}, (previous, next) => previous.preset === next.preset && previous.source === next.source && previous.scopeId === next.scopeId && previous.selected === next.selected)

function AtmospherePreview({ atmosphere, seconds, width, height, layerId }: { atmosphere: Atmosphere; seconds: number; width: number; height: number; layerId: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const pixelWidth = Math.max(1, Math.round(width))
  const pixelHeight = Math.max(1, Math.round(height))
  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    context.clearRect(0, 0, canvas.width, canvas.height)
    context.save()
    context.translate(canvas.width / 2, canvas.height / 2)
    drawAtmosphere(context, atmosphere, seconds, canvas.width, canvas.height)
    context.restore()
  }, [atmosphere, seconds, pixelWidth, pixelHeight])
  return <canvas ref={canvasRef} data-layer-id={layerId} width={pixelWidth} height={pixelHeight} className="h-full w-full" />
}

export function SceneAnimatorPanel() {
  const outputs = useStore(s => s.outputs)
  const loadOutputs = useStore(s => s.loadOutputs)
  const workspace = useStore(s => s.activeWorkspace)
  const setGenerationMode = useStore(s => s.setGenerationMode)
  const setSidebarMode = useStore(s => s.setSidebarMode)
  const setSidebarOpen = useStore(s => s.setSidebarOpen)
  const selectedSpeechModel = useStore(s => s.selectedModelPerAudioSubMode.speech ?? 'kugelaudio_0_open')
  const [scene, setScene] = useState<AnimatorScene>(blankScene)
  const sceneRef = useRef(scene)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [picker, setPicker] = useState<'model' | 'media' | null>(null)
  const [playing, setPlaying] = useState(false)
  const [recording, setRecording] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [progress, setProgress] = useState(0)
  const [flash, setFlash] = useState<{ x: number; y: number } | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [motionText, setMotionText] = useState('')
  const [reassignId, setReassignId] = useState<string | null>(null)
  const [jsonOpen, setJsonOpen] = useState(false)
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [narrativeTemplateId, setNarrativeTemplateId] = useState<NarrativeSceneId>('inner-thought')
  const [narrativeHero, setNarrativeHero] = useState('')
  const [narrativePlate, setNarrativePlate] = useState('')
  const [narrativePlateLoopReady, setNarrativePlateLoopReady] = useState(false)
  const [narrativeProp, setNarrativeProp] = useState('')
  const [narrativeForeground, setNarrativeForeground] = useState('')
  const [narrativeMood, setNarrativeMood] = useState<NonNullable<NarrativeTemplateInput['controls']>['mood']>('calm')
  const [narrativeIntensity, setNarrativeIntensity] = useState<1 | 2 | 3>(2)
  const [narrativeDirection, setNarrativeDirection] = useState<NonNullable<NarrativeTemplateInput['controls']>['direction']>('right')
  const [narrativeCamera, setNarrativeCamera] = useState<NonNullable<NarrativeTemplateInput['controls']>['camera']>('restrained')
  const [narrativePalette, setNarrativePalette] = useState<NonNullable<NarrativeTemplateInput['controls']>['palette']>('natural')
  const [narrativeVoiceSpace, setNarrativeVoiceSpace] = useState<NonNullable<NarrativeTemplateInput['controls']>['voiceSpace']>('center')
  const [copilotIntent, setCopilotIntent] = useState('')
  const [copilotBusy, setCopilotBusy] = useState(false)
  const [copilotProposal, setCopilotProposal] = useState<SceneCopilotProposal | null>(null)
  const [copilotProposalRevision, setCopilotProposalRevision] = useState<number | null>(null)
  const [copilotError, setCopilotError] = useState<string | null>(null)
  const [copilotListening, setCopilotListening] = useState(false)
  const [sceneCopilotIntent, setSceneCopilotIntent] = useState('')
  const [sceneCopilotBusy, setSceneCopilotBusy] = useState(false)
  const [sceneCopilotProposal, setSceneCopilotProposal] = useState<SceneCopilotProposal | null>(null)
  const [sceneCopilotProposalRevision, setSceneCopilotProposalRevision] = useState<number | null>(null)
  const [sceneCopilotError, setSceneCopilotError] = useState<string | null>(null)
  const [sceneAudioPrompt, setSceneAudioPrompt] = useState('')
  const [sceneAudioBusy, setSceneAudioBusy] = useState(false)
  const [sceneAudioError, setSceneAudioError] = useState<string | null>(null)
  const [chainFromPlayhead, setChainFromPlayhead] = useState(false)
  const [selectedKeyframeId, setSelectedKeyframeId] = useState<string | null>(null)
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [historyRevision, setHistoryRevision] = useState(0)
  const historyRevisionRef = useRef(0)
  const [lastAutosaveAt, setLastAutosaveAt] = useState<number | null>(null)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [cylinderCompareOpen, setCylinderCompareOpen] = useState(false)
  const [previewWidth, setPreviewWidth] = useState(1280)
  const [clipsByLayer, setClipsByLayer] = useState<Record<string, string[]>>({})
  const [clipDurationsByLayer, setClipDurationsByLayer] = useState<Record<string, number>>({})
  const canvasRef = useRef<HTMLDivElement>(null)
  const animationRef = useRef<number | null>(null)
  const recordingAnimationRef = useRef<number | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const recipeContextRef = useRef<{ prompt: string; recipe: SceneRecipe } | null>(null)
  const recordingStreamRef = useRef<MediaStream | null>(null)
  const modelInputRef = useRef<HTMLInputElement>(null)
  const mediaInputRef = useRef<HTMLInputElement>(null)
  const overlayInputRef = useRef<HTMLInputElement>(null)
  const motionInputRef = useRef<HTMLInputElement>(null)
  const sceneInputRef = useRef<HTMLInputElement>(null)
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({})
  const flashTimerRef = useRef<number | null>(null)
  const gestureRef = useRef<Gesture | null>(null)
  const localFilesRef = useRef<Record<string, File>>({})
  const keyframeClipboardRef = useRef('')
  const pastScenesRef = useRef<AnimatorScene[]>([])
  const futureScenesRef = useRef<AnimatorScene[]>([])
  const lastHistoryAtRef = useRef(0)
  const progressRef = useRef(progress)
  progressRef.current = progress
  const selected = scene.layers.find(layer => layer.id === selectedId) ?? null
  const activeNarrativeId = scene.narrative?.templateId ?? narrativeTemplateId
  const copilotSuggestions = selected ? (() => {
    if (selected.type === 'camera') return ['Keep the camera restrained for the whole shot', 'Add a very gentle drift without zooming']
    if (activeNarrativeId === 'inner-thought') return ['Move it left and make it look thoughtful', 'Leave space for an inner voice on the right']
    if (activeNarrativeId === 'run-travel-parallax') return ['Keep the subject stable and add a subtle run-like bob', 'Make this foreground layer move faster than the world']
    if (selected.type === 'model3d') return ['Turn it slightly to camera right', 'Give it a gentle living drift']
    return ['Move it left a little', 'Make its look calmer and more cinematic']
  })() : []
  const composition = { ...DEFAULT_COMPOSITION, ...scene.composition }
  const fps: SceneFrameRate = scene.fps === 60 ? 60 : 30
  const snapCoordinate = (value: number) => composition.snap ? Math.round(value / Math.max(1, composition.gridSize)) * Math.max(1, composition.gridSize) : value
  const generatedModels = outputs.filter(output => output.type === 'model3d' && /\.glb$/i.test(output.name))
  const generatedMedia = outputs.filter(output => output.type === 'image' || output.type === 'video')
  const generatedAudio = outputs.filter(output => output.type === 'audio')
  const narrativeVisuals = outputs.filter(output => output.type === 'model3d' || output.type === 'image' || output.type === 'video')
  const narrativeTemplate = getNarrativeTemplate(narrativeTemplateId)!
  const narrativeAssetByName = (name: string) => narrativeVisuals.find(asset => asset.name === name)
  const narrativeSuitability = (role: 'hero' | 'plate' | 'prop' | 'foreground', name: string) => {
    const asset = narrativeAssetByName(name)
    const type = asset?.type === 'image' || asset?.type === 'video' || asset?.type === 'model3d' ? asset.type : undefined
    return assessNarrativeAsset(role, type, name)
  }
  const previewShortSide = Math.min(previewWidth, previewWidth * scene.height / Math.max(1, scene.width))
  const selectedModelId = selected?.type === 'model3d' ? selected.id : null
  const selectedModelSource = selected?.type === 'model3d' ? selected.source : null
  const selectedModelClip = selected?.type === 'model3d' ? selected.animation.clip : undefined

  const syncSceneMedia = useCallback((sceneSeconds: number) => {
    sceneRef.current.layers.filter(layer => layer.type === 'model3d').forEach(layer => {
      findLayerElements(canvasRef.current, layer.id).forEach(element => {
        const viewer = element as ModelViewerAnimationElement
        if (typeof viewer.pause !== 'function') return
        if (!layer.animation.clip) { viewer.pause(); if (Number.isFinite(viewer.currentTime)) viewer.currentTime = 0; return }
        const applyTime = () => {
          viewer.pause()
          const duration = finiteNumber(viewer.duration, 0)
          if (duration > 0) viewer.currentTime = getSceneClipTime(layer, sceneSeconds, duration)
        }
        if (viewer.animationName !== layer.animation.clip) { viewer.animationName = layer.animation.clip; queueMicrotask(applyTime) }
        else applyTime()
      })
    })
    sceneRef.current.layers.filter(layer => layer.type === 'video').forEach(layer => {
      findLayerElements(canvasRef.current, layer.id).forEach(element => {
        if (!(element instanceof HTMLVideoElement)) return
        element.pause()
        const duration = finiteNumber(element.duration, 0)
        if (duration <= 0) return
        const layerTime = sceneTimeToLayerTime(layer, sceneSeconds)
        const finalFrame = Math.max(0, duration - 1 / fps)
        const target = layer.animation.loop ? layerTime % duration : Math.min(finalFrame, layerTime)
        if (Math.abs(element.currentTime - target) > 1 / (fps * 2)) {
          try { element.currentTime = target } catch { /* Metadata can disappear while a source is being reassigned. */ }
        }
      })
    })
  }, [fps])

  useEffect(() => { void import('@google/model-viewer') }, [])
  useEffect(() => {
    const element = canvasRef.current
    if (!element) return
    const update = () => setPreviewWidth(Math.max(1, element.getBoundingClientRect().width))
    update()
    if (typeof ResizeObserver === 'undefined') { window.addEventListener('resize', update); return () => window.removeEventListener('resize', update) }
    const observer = new ResizeObserver(update); observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    const layer = sceneRef.current.layers.find(item => item.id === selectedId)
    setSelectedPresetId('')
    setCopilotProposal(null); setCopilotError(null)
    setSelectedKeyframeId(id => id && layer && getSceneKeyframes(layer).some(frame => frame.id === id) ? id : null)
    setSelectedEventId(id => id && layer && getSceneEvents(layer).some(event => event.id === id) ? id : null)
  }, [selectedId])
  useEffect(() => {
    // Playback and recording synchronize media in their own animation loops.
    // Avoid seeking every GLB/video twice per frame, which can make otherwise
    // smooth motion appear to vibrate.
    if (playing || recording) return
    // The scene object intentionally resynchronizes clips after inspector edits.
    const frame = requestAnimationFrame(() => syncSceneMedia(progress * scene.duration))
    return () => cancelAnimationFrame(frame)
  }, [playing, progress, recording, scene, syncSceneMedia])
  // Rigged GLBs expose their baked clips through model-viewer's
  // availableAnimations; poll briefly after selection until the model loads.
  useEffect(() => {
    if (!selectedModelId) return
    let timer: number | null = null
    const read = () => {
      const element = findLayerElement(canvasRef.current, selectedModelId) as ModelViewerAnimationElement | null
      const clips = element?.availableAnimations ?? []
      if (clips.length > 0) {
        setClipsByLayer(current => JSON.stringify(current[selectedModelId]) === JSON.stringify(clips) ? current : { ...current, [selectedModelId]: clips })
        const duration = finiteNumber(element?.duration, 0)
        if (duration > 0) {
          setClipDurationsByLayer(current => current[selectedModelId] === duration ? current : { ...current, [selectedModelId]: duration })
          syncSceneMedia(progressRef.current * sceneRef.current.duration)
        }
        if ((!selectedModelClip || duration > 0) && timer !== null) window.clearInterval(timer)
      }
    }
    read()
    timer = window.setInterval(read, 800)
    return () => { if (timer !== null) window.clearInterval(timer) }
  }, [selectedModelId, selectedModelSource, selectedModelClip, syncSceneMedia])
  useEffect(() => { void loadOutputs() }, [loadOutputs])
  useEffect(() => () => {
    if (animationRef.current) cancelAnimationFrame(animationRef.current)
    if (recordingAnimationRef.current) cancelAnimationFrame(recordingAnimationRef.current)
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    const recorder = mediaRecorderRef.current
    if (recorder) {
      recorder.ondataavailable = null; recorder.onerror = null; recorder.onstop = null
      if (recorder.state !== 'inactive') { try { recorder.stop() } catch { /* Recorder may already be shutting down. */ } }
    }
    recordingStreamRef.current?.getTracks().forEach(track => track.stop())
  }, [])

  useEffect(() => { sceneRef.current = scene }, [scene])
  useEffect(() => { historyRevisionRef.current = historyRevision }, [historyRevision])
  const replaceScene = (next: AnimatorScene) => { sceneRef.current = next; setScene(next) }
  const updateScene = (updater: (current: AnimatorScene) => AnimatorScene) => {
    const current = sceneRef.current
    let next = updater(current)
    if (next === current) return
    const removesLockedLayer = current.layers.some(layer => layer.locked && !next.layers.some(candidate => candidate.id === layer.id))
    if (removesLockedLayer) { setMessage('Unlock the layer before deleting it.'); return }
    const removedIds = new Set(current.layers.filter(layer => !next.layers.some(candidate => candidate.id === layer.id)).map(layer => layer.id))
    if (removedIds.size > 0) next = { ...next, layers: next.layers.map(layer => ({ ...layer, relationship: layer.relationship && removedIds.has(layer.relationship.targetLayerId) ? undefined : layer.relationship, animation: { ...layer.animation, orbit: layer.animation.orbit && removedIds.has(layer.animation.orbit.targetLayerId) ? undefined : layer.animation.orbit } })) }
    const now = Date.now()
    if (pastScenesRef.current.length === 0 || now - lastHistoryAtRef.current > 350) {
      pastScenesRef.current.push(current)
      if (pastScenesRef.current.length > HISTORY_LIMIT) pastScenesRef.current.shift()
    }
    lastHistoryAtRef.current = now
    futureScenesRef.current = []
    sceneRef.current = next
    setScene(next)
    setHistoryRevision(value => value + 1)
  }
  const undoScene = () => {
    const previous = pastScenesRef.current.pop()
    if (!previous) return
    futureScenesRef.current.push(sceneRef.current)
    replaceScene(previous); lastHistoryAtRef.current = 0; setHistoryRevision(value => value + 1)
    setSelectedId(id => id && previous.layers.some(layer => layer.id === id) ? id : null); setSelectedKeyframeId(null); setSelectedEventId(null); setMessage('Undo')
  }
  const redoScene = () => {
    const next = futureScenesRef.current.pop()
    if (!next) return
    pastScenesRef.current.push(sceneRef.current)
    replaceScene(next); lastHistoryAtRef.current = 0; setHistoryRevision(value => value + 1)
    setSelectedId(id => id && next.layers.some(layer => layer.id === id) ? id : null); setSelectedKeyframeId(null); setSelectedEventId(null); setMessage('Redo')
  }
  const updateLayer = (id: string, updater: (layer: AnimatorLayer) => AnimatorLayer) => updateScene(current => {
    const target = current.layers.find(layer => layer.id === id)
    if (!target) return current
    let updated = reconcileLegacyKeyframeUpdate(target, updater(target))
    if (target.relationship?.type === 'follow' && updated.relationship === target.relationship) {
      const dx = updated.transform.x - target.transform.x
      const dy = updated.transform.y - target.transform.y
      if (dx || dy) updated = { ...updated, relationship: { ...target.relationship, offsetX: (target.relationship.offsetX ?? 0) + dx, offsetY: (target.relationship.offsetY ?? 0) + dy } }
    }
    if (target.locked) {
      const changedKeys = (Object.keys(updated) as Array<keyof AnimatorLayer>).filter(key => updated[key] !== target[key])
      if (changedKeys.some(key => key !== 'visible' && key !== 'locked')) return current
    }
    const activatesCamera = updated.type === 'camera' && updated.visible
    return { ...current, layers: current.layers.map(layer => layer.id === id ? updated : activatesCamera && layer.type === 'camera' ? { ...layer, visible: false } : layer) }
  })
  const updateLayerDuration = (id: string, value: number, minimum = .1) => updateScene(current => {
    if (current.layers.find(layer => layer.id === id)?.locked) return current
    const duration = Math.max(minimum, value)
    return {
      ...current,
      duration: Math.max(current.duration, duration),
      layers: current.layers.map(layer => {
        if (layer.id !== id) return layer
        if (layer.locked) return layer
        const previousDuration = Math.max(.1, layer.animation.duration)
        const keyframes = layer.animation.keyframes?.map(frame => ({ ...frame, time: frame.time * duration / previousDuration }))
        const events = layer.animation.events?.map(event => ({ ...event, time: event.time * duration / previousDuration }))
        return { ...layer, animation: { ...layer.animation, duration, keyframes, events, trimStart: (layer.animation.trimStart ?? 0) * duration / previousDuration, trimEnd: (layer.animation.trimEnd ?? previousDuration) * duration / previousDuration } }
      }),
    }
  })
  const updateLayerTiming = (id: string, patch: Partial<Pick<AnimatorLayer['animation'], 'offset' | 'speed' | 'loop' | 'trimStart' | 'trimEnd'>>) => updateScene(current => {
    if (current.layers.find(layer => layer.id === id)?.locked) return current
    let sceneEnd = current.duration
    const layers = current.layers.map(layer => {
      if (layer.id !== id) return layer
      if (layer.locked) return layer
      const updated = withNormalizedSceneTiming({ ...layer, animation: { ...layer.animation, ...patch } }) as AnimatorLayer
      const timing = getSceneLayerTiming(updated)
      sceneEnd = Math.max(sceneEnd, timing.offset + timing.span / timing.speed)
      return updated
    })
    return { ...current, duration: sceneEnd, layers }
  })
  const updateLayerEndpoint = (id: string, endpoint: 'start' | 'end', patch: Partial<Point>) => updateLayer(id, layer => {
    if (!layer.animation.keyframes?.length) return { ...layer, animation: { ...layer.animation, [endpoint]: { ...layer.animation[endpoint], ...patch } } }
    const frames = getSceneKeyframes(layer)
    const index = endpoint === 'start' ? 0 : frames.length - 1
    const keyframe = frames[index]
    frames[index] = {
      ...keyframe,
      ...patch,
      opacity: patch.opacity ?? keyframe.opacity,
      rotation: patch.rotation ?? keyframe.rotation,
    }
    return withSceneKeyframes(layer, frames) as AnimatorLayer
  })
  const updateLayerCurve = (id: string, curve: SceneCurve) => updateLayer(id, layer => ({
    ...layer,
    animation: {
      ...layer.animation,
      curve,
      keyframes: layer.animation.keyframes?.map(frame => ({ ...frame, curve })),
    },
  }))
  const setLayerVisibility = (id: string, visible: boolean) => updateScene(current => {
    const target = current.layers.find(layer => layer.id === id)
    return {
      ...current,
      layers: current.layers.map(layer => ({
        ...layer,
        visible: target?.type === 'camera' && visible && layer.type === 'camera' ? layer.id === id : layer.id === id ? visible : layer.visible,
      })),
    }
  })
  const flashAt = (x: number, y: number, layerId = selectedId) => {
    const layer = scene.layers.find(item => item.id === layerId)
    const point = layer && isVisualLayer(layer)
      ? applyCameraTransform({ x, y, scale: 1, opacity: 1, rotation: 0, z: layer.z }, layer, progress)
      : { x, y }
    setFlash({ x: point.x, y: point.y })
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    flashTimerRef.current = window.setTimeout(() => setFlash(null), 550)
  }
  const addLayer = (type: VisualLayerType, source: string, name: string, thumbnail?: string, localFile?: File) => {
    const id = uid()
    if (localFile) localFilesRef.current[id] = localFile
    updateScene(current => {
      const foregroundCount = current.layers.filter(layer => layer.type === 'model3d' || layer.type === 'overlay').length
      const offset = type === 'model3d' || type === 'overlay' ? Math.min(24, foregroundCount * 6) : 0
      const scale = type === 'model3d' ? .7 : 1
      const layer: AnimatorLayer = { id, name, type, source, thumbnail, visible: true, z: 0, parallax: 1, transform: { x: 50 + offset, y: 50 + offset / 3, scale, opacity: 1, rotation: 0, rotationX: 75, rotationY: 0 }, animation: { start: makePoint(50 + offset, 50 + offset / 3, scale), end: makePoint(50 + offset, 50 + offset / 3, scale), duration: current.duration, curve: 'linear', spin: type === 'model3d', rotationSpeed: 35 } }
      const ordered = normalizeZ(current.layers)
      const layers = type === 'image' || type === 'video' ? [layer, ...ordered] : [...ordered, layer]
      return { ...current, layers: normalizeZ(layers) }
    })
    setSelectedId(id); setAddOpen(false); setPicker(null)
  }
  const addAtmosphere = (kind: SceneAtmosphereKind) => {
    const id = uid()
    const preset = ATMOSPHERE_PRESETS[kind]
    const opacity = ATMOSPHERE_OPACITY[kind]
    const luminous = kind === 'embers' || kind === 'fireflies' || kind === 'bokeh' || kind === 'sparkles' || kind === 'bubbles' || kind === 'speedlines'
    updateScene(current => {
      const layer: AnimatorLayer = {
        id,
        name: ATMOSPHERE_LABELS[kind],
        type: 'effect',
        source: `maestro-effect:${kind}`,
        visible: true,
        z: Math.max(0, ...current.layers.map(item => item.z)) + 10,
        fill: true,
        parallax: 0,
        atmosphere: { ...preset },
        effects: { ...DEFAULT_EFFECTS, blendMode: luminous ? 'screen' : 'normal' },
        transform: { x: 50, y: 50, scale: 1, opacity, rotation: 0 },
        animation: {
          start: { x: 50, y: 50, scale: 1, opacity, rotation: 0 },
          end: { x: 50, y: 50, scale: 1, opacity, rotation: 0 },
          duration: current.duration,
          curve: 'linear',
        },
      }
      return { ...current, layers: normalizeZ([...current.layers, layer]) }
    })
    setSelectedId(id); setAddOpen(false); setPicker(null)
  }
  const addCamera = () => {
    const id = uid()
    updateScene(current => {
      const cameraCount = current.layers.filter(layer => layer.type === 'camera').length
      const camera: AnimatorLayer = {
        id,
        name: `Camera ${cameraCount + 1}`,
        type: 'camera',
        source: '',
        visible: true,
        z: 0,
        transform: { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 },
        animation: {
          start: { x: 50, y: 50, scale: 1, rotation: 0 },
          end: { x: 50, y: 50, scale: 1, rotation: 0 },
          duration: current.duration,
          curve: 'ease',
        },
      }
      const layers = current.layers.map(layer => layer.type === 'camera' ? { ...layer, visible: false } : layer)
      return { ...current, layers: normalizeZ([...layers, camera]) }
    })
    setSelectedId(id); setAddOpen(false); setPicker(null); setProgress(0)
  }
  const duplicateLayer = (id: string) => {
    const original = sceneRef.current.layers.find(layer => layer.id === id)
    if (!original) return
    const duplicateId = uid()
    if (localFilesRef.current[id]) localFilesRef.current[duplicateId] = localFilesRef.current[id]
    updateScene(current => {
      const source = current.layers.find(layer => layer.id === id)
      if (!source) return current
      const clone = structuredClone(source) as AnimatorLayer
      clone.id = duplicateId
      clone.name = `${source.name} copy`
      clone.locked = false
      clone.visible = source.type === 'camera' ? false : source.visible
      clone.z = source.z + 5
      clone.animation.keyframes = clone.animation.keyframes?.map(frame => ({ ...frame, id: uid() }))
      clone.animation.events = clone.animation.events?.map(event => ({ ...event, id: uid() }))
      if (isVisualLayer(clone)) {
        clone.transform = { ...clone.transform, x: clone.transform.x + 3, y: clone.transform.y + 3 }
        clone.animation = mapSceneAnimationPoints(clone, point => ({ ...point, x: point.x + 3, y: point.y + 3 }))
      }
      return { ...current, layers: normalizeZ([...current.layers, clone]) }
    })
    setSelectedId(duplicateId); setSelectedKeyframeId(null); setSelectedEventId(null); setMessage(`Duplicated ${original.name}.`)
  }
  const addOrReassign = (type: VisualLayerType, file: File) => {
    const source = URL.createObjectURL(file)
    if (reassignId) {
      localFilesRef.current[reassignId] = file
      updateLayer(reassignId, layer => ({ ...layer, type, source, name: file.name, missingAsset: false }))
      setReassignId(null)
    } else addLayer(type, source, file.name, undefined, file)
  }
  const translateLayer = (id: string, x: number, y: number, useSnap = true) => updateLayer(id, layer => {
    const nextX = useSnap ? snapCoordinate(x) : x; const nextY = useSnap ? snapCoordinate(y) : y
    const dx = nextX - layer.transform.x; const dy = nextY - layer.transform.y
    return { ...layer, transform: { ...layer.transform, x: nextX, y: nextY }, animation: mapSceneAnimationPoints(layer, point => ({ ...point, x: point.x + dx, y: point.y + dy })) }
  })
  const resizeLayer = (id: string, scale: number) => updateLayer(id, layer => ({ ...layer, transform: { ...layer.transform, scale }, animation: mapSceneAnimationPoints(layer, point => ({ ...point, scale })) }))
  const startGesture = (event: ReactPointerEvent<HTMLElement>, layer: AnimatorLayer, mode: Gesture['mode']) => {
    if (layer.locked) { event.preventDefault(); event.stopPropagation(); setSelectedId(layer.id); setMessage('Unlock the layer before moving it.'); return }
    event.preventDefault(); event.stopPropagation(); setSelectedId(layer.id)
    gestureRef.current = { id: layer.id, mode, startX: event.clientX, startY: event.clientY, x: layer.transform.x, y: layer.transform.y, scale: layer.transform.scale, rotationX: layer.transform.rotationX ?? 75, rotationY: layer.transform.rotationY ?? 0 }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const moveGesture = (event: ReactPointerEvent<HTMLElement>) => {
    const gesture = gestureRef.current; const bounds = canvasRef.current?.getBoundingClientRect(); if (!gesture || !bounds) return
    if (gesture.mode === 'move') {
      const screenX = (event.clientX - gesture.startX) / bounds.width * 100
      const screenY = (event.clientY - gesture.startY) / bounds.height * 100
      const view = cameraState(progress); const radians = view.rotation * Math.PI / 180; const cos = Math.cos(radians); const sin = Math.sin(radians); const zoom = Math.max(.05, view.scale); const aspect = scene.width / Math.max(1, scene.height)
      const x = gesture.x + (screenX * cos - screenY / aspect * sin) / zoom
      const y = gesture.y + (screenX * aspect * sin + screenY * cos) / zoom
      translateLayer(gesture.id, x, y); flashAt(x, y, gesture.id)
    }
    else if (gesture.mode === 'resize') { const zoom = Math.max(.05, cameraState(progress).scale); resizeLayer(gesture.id, Math.max(.05, Math.min(3, gesture.scale + (event.clientX - gesture.startX + event.clientY - gesture.startY) / Math.min(bounds.width, bounds.height) / zoom))) }
    else updateLayer(gesture.id, layer => ({ ...layer, transform: { ...layer.transform, rotationY: gesture.rotationY + (event.clientX - gesture.startX) * .8, rotationX: Math.max(1, Math.min(179, gesture.rotationX + (event.clientY - gesture.startY) * .5)) } }))
  }
  const endGesture = () => { gestureRef.current = null }
  const baseLayerState = (layer: AnimatorLayer, time: number): LayerState => ({ ...evaluateSceneLayer(layer, sceneTimeToLayerTime(layer, time * scene.duration)), z: layer.z })
  const activeCameraLayer = () => [...scene.layers].filter(layer => layer.type === 'camera' && layer.visible).sort((a, b) => b.z - a.z)[0]
  const cameraState = (time: number): LayerState => {
    const camera = activeCameraLayer()
    return camera ? layerState(camera, time) : { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0, z: 0 }
  }
  const applyCameraTransform = (state: LayerState, layer: AnimatorLayer, time: number): LayerState => {
    const camera = activeCameraLayer()
    if (!camera || layer.type === 'camera' || layer.type === 'effect') return state
    const view = layerState(camera, time)
    const parallax = effectiveParallax(layer)
    const dx = state.x - 50 - (view.x - 50) * parallax
    const dy = state.y - 50 - (view.y - 50) * parallax
    const radians = view.rotation * Math.PI / 180
    const cos = Math.cos(radians); const sin = Math.sin(radians)
    const zoom = Math.max(.05, view.scale)
    const aspect = scene.width / Math.max(1, scene.height)
    return {
      ...state,
      // Rotate in scene pixels rather than percent-space so portrait and
      // landscape shots keep a physically correct camera roll.
      x: 50 + (dx * cos + dy / aspect * sin) * zoom,
      y: 50 + (-dx * aspect * sin + dy * cos) * zoom,
      scale: state.scale * zoom,
      rotation: state.rotation - view.rotation,
    }
  }
  function effectiveParallax(layer: AnimatorLayer, visited = new Set<string>()): number {
    if (visited.has(layer.id)) return layer.parallax ?? 1
    const nextVisited = new Set(visited); nextVisited.add(layer.id)
    const targetId = layer.relationship?.targetLayerId ?? layer.animation.orbit?.targetLayerId
    const target = targetId && scene.layers.find(item => item.id === targetId)
    return target && isVisualLayer(target) ? effectiveParallax(target, nextVisited) : layer.parallax ?? 1
  }
  function layerState(layer: AnimatorLayer, time = progress, visited = new Set<string>(), applyShake = true): LayerState {
    let state = baseLayerState(layer, time)
    if (visited.has(layer.id)) return state
    const nextVisited = new Set(visited); nextVisited.add(layer.id)
    const relationship = layer.relationship
    const relationshipTarget = relationship && scene.layers.find(item => item.id === relationship.targetLayerId)
    if (relationship && relationshipTarget && isVisualLayer(relationshipTarget) && !nextVisited.has(relationshipTarget.id)) {
      const targetState = layerState(relationshipTarget, time, nextVisited, applyShake)
      if (relationship.type === 'parent') {
        const targetOrigin = layerState(relationshipTarget, 0, nextVisited, applyShake)
        const scaleRatio = targetState.scale / Math.max(.01, targetOrigin.scale)
        const angle = (targetState.rotation - targetOrigin.rotation) * Math.PI / 180
        const relativeX = (state.x - targetOrigin.x) * scene.width
        const relativeY = (state.y - targetOrigin.y) * scene.height
        const rotatedX = (relativeX * Math.cos(angle) - relativeY * Math.sin(angle)) * scaleRatio
        const rotatedY = (relativeX * Math.sin(angle) + relativeY * Math.cos(angle)) * scaleRatio
        state = {
          ...state,
          x: targetState.x + rotatedX / scene.width,
          y: targetState.y + rotatedY / scene.height,
          scale: state.scale * scaleRatio,
          rotation: state.rotation + targetState.rotation - targetOrigin.rotation,
        }
      } else if (relationship.type === 'follow') {
        const strength = Math.max(0, Math.min(1, relationship.strength ?? 1))
        const targetX = targetState.x + (relationship.offsetX ?? 0)
        const targetY = targetState.y + (relationship.offsetY ?? 0)
        state = { ...state, x: state.x + (targetX - state.x) * strength, y: state.y + (targetY - state.y) * strength }
      } else {
        const dx = (targetState.x - state.x) * scene.width
        const dy = (targetState.y - state.y) * scene.height
        state = { ...state, rotation: Math.atan2(dy, dx) * 180 / Math.PI + (relationship.rotationOffset ?? 0) }
      }
    }
    const orbit = layer.animation.orbit
    const target = orbit && scene.layers.find(item => item.id === orbit.targetLayerId)
    if (orbit && target && isVisualLayer(target) && target.id !== layer.id && !nextVisited.has(target.id)) {
      const targetState = layerState(target, time, nextVisited, applyShake)
      const orbitProgress = sceneLayerMotionProgress(layer, time * scene.duration)
      const angle = orbit.phase * Math.PI / 180 + orbitProgress * orbit.turns * Math.PI * 2
      const depth = Math.sin(angle)
      const centerX = targetState.x + (orbit.centerOffsetX ?? 0)
      const centerY = targetState.y + (orbit.centerOffsetY ?? 0)
      state = { ...state, x: centerX + Math.cos(angle) * orbit.radiusX, y: centerY + depth * orbit.radiusY, scale: state.scale * (1 + depth * .12), z: target.z + (depth >= 0 ? 1 : -1) }
    }
    if (applyShake && layer.type === 'camera' && layer.animation.shake?.amount) {
      const amount = Math.max(0, Math.min(8, layer.animation.shake.amount))
      const frequency = Math.max(.1, Math.min(30, layer.animation.shake.frequency))
      const sceneSeconds = time * scene.duration
      const timing = getSceneLayerTiming(layer)
      const elapsed = Math.max(0, sceneSeconds - timing.offset) * timing.speed
      if (sceneSeconds >= timing.offset && (timing.loop || elapsed <= timing.span)) {
        const localTime = sceneTimeToLayerTime(layer, sceneSeconds)
        const shakeStart = layer.animation.shake.startTime ?? timing.trimStart
        const shakeEnd = layer.animation.shake.endTime ?? timing.trimEnd
        if (localTime < shakeStart || localTime > shakeEnd) return state
        const localElapsed = localTime - shakeStart
        const phase = localElapsed * frequency * Math.PI * 2 + (layer.animation.shake.seed ?? 0)
        state = { ...state, x: state.x + Math.sin(phase) * amount, y: state.y + Math.sin(phase * 1.37 + 1.2) * amount * .65, rotation: state.rotation + Math.sin(phase * .73 + .4) * amount * .35 }
      }
    }
    return state
  }
  const renderedLayerStates = (layer: AnimatorLayer, time = progress) => {
    const orbitCount = layer.animation.orbit ? Math.round(boundedNumber(layer.animation.orbit.count, 1, 1, 12)) : 1
    const offsets = stripOffsets(layer, time * sceneRef.current.duration)
    const instances: LayerState[] = []
    for (let orbitIndex = 0; orbitIndex < orbitCount; orbitIndex += 1) {
      const orbit = layer.animation.orbit
      const instanceLayer = orbit && orbitCount > 1 ? { ...layer, animation: { ...layer.animation, orbit: { ...orbit, phase: orbit.phase + orbitIndex * 360 / orbitCount } } } : layer
      let orbitState = layerState(instanceLayer, time)
      if (layer.type === 'model3d' && layer.animation.spin) {
        const timing = getSceneLayerTiming(layer)
        const localSeconds = sceneTimeToLayerTime(layer, time * scene.duration) - timing.trimStart
        orbitState = { ...orbitState, modelYaw: localSeconds * (layer.animation.rotationSpeed ?? 35) }
      }
      for (const offset of offsets) {
        let state = { ...orbitState, x: orbitState.x + offset.x, y: orbitState.y + offset.y }
        if (orbit && orbit.facing && orbit.facing !== 'fixed') {
          const target = scene.layers.find(item => item.id === orbit.targetLayerId)
          if (target && isVisualLayer(target)) {
            const targetState = layerState(target, time)
            const centerX = targetState.x + (orbit.centerOffsetX ?? 0)
            const centerY = targetState.y + (orbit.centerOffsetY ?? 0)
            const angle = Math.atan2((centerY - state.y) * scene.height, (centerX - state.x) * scene.width) * 180 / Math.PI
            const facingAngle = angle + (orbit.facing === 'outward' ? 180 : 0)
            state = layer.type === 'model3d'
              ? { ...state, modelYaw: facingAngle }
              : { ...state, rotation: facingAngle }
          }
        }
        instances.push(applyCameraTransform(state, layer, time))
      }
    }
    // Each 3D copy is a live WebGL context. orbit(12) × strip(12) = 144
    // viewers, which locks the GPU and can freeze the host.
    const cap = layer.type === 'model3d' ? 4 : 24
    return instances.slice(0, cap)
  }
  const seamCoverStates = (layer: AnimatorLayer, time = progress) => {
    const strip = normalizedStrip(layer.strip)
    if (!strip.enabled || !strip.seamOccluder.enabled) return []
    const offsets = stripOffsets({ ...layer, strip: { ...strip, phase: strip.phase + strip.spacing / 2 } }, time * sceneRef.current.duration)
    const base = layerState(layer, time)
    return offsets.map(offset => applyCameraTransform({
      ...base,
      x: base.x + offset.x,
      y: 82,
      scale: strip.seamOccluder.scale,
      opacity: Math.min(1, base.opacity * strip.seamOccluder.opacity),
    }, layer, time))
  }
  const moveLayerZ = (id: string, direction: 1 | -1) => updateScene(current => {
    const layers = normalizeZ(current.layers)
    const moving = layers.find(layer => layer.id === id)
    if (!moving || moving.locked) return current
    // Cameras have a priority order of their own and must not consume a
    // foreground/background click intended for a visual layer.
    const peers = layers.filter(layer => moving.type === 'camera' ? layer.type === 'camera' : isVisualLayer(layer))
    const index = peers.findIndex(layer => layer.id === id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= peers.length) return current
    const other = peers[target]
    if (other.locked) return current
    const swapped = layers.map(layer => layer.id === moving.id ? { ...layer, z: other.z } : layer.id === other.id ? { ...layer, z: moving.z } : layer)
    return { ...current, layers: assignZ(swapped.sort((a, b) => a.z - b.z)) }
  })
  const sendToBack = (id: string) => updateScene(current => {
    const layers = normalizeZ(current.layers)
    const layer = layers.find(item => item.id === id)
    if (!layer || layer.locked) return current
    return { ...current, layers: assignZ([layer, ...layers.filter(item => item.id !== id)]) }
  })
  const resetSceneMedia = () => syncSceneMedia(0)
  const animate = (done?: () => void) => {
    const started = performance.now()
    resetSceneMedia(); setPlaying(true)
    const frame = (now: number) => {
      const elapsed = Math.min(scene.duration, (now - started) / 1000)
      const finished = elapsed >= scene.duration
      // Preview follows the display refresh rate. The selected 30/60 FPS is an
      // export cadence, not a reason to quantize interactive playback.
      const next = finished ? 1 : elapsed / scene.duration
      syncSceneMedia(next * scene.duration); setProgress(next)
      if (!finished) animationRef.current = requestAnimationFrame(frame)
      else { setPlaying(false); Object.values(videoRefs.current).forEach(video => video?.pause()); done?.() }
    }
    animationRef.current = requestAnimationFrame(frame)
  }
  const play = () => { if (animationRef.current) cancelAnimationFrame(animationRef.current); setProgress(0); animate() }
  const appendPresetAtPlayhead = (layer: AnimatorLayer, preset: Pick<Preset, 'start' | 'end' | 'duration' | 'curve'> | CameraPreset) => {
    const sceneTime = Math.round(progress * scene.duration * fps) / fps
    const timing = getSceneLayerTiming(layer)
    // Do not clamp to the old trim-out: a layer that already ended must hold
    // its last pose until the requested scene frame, then continue there.
    const localTime = timing.trimStart + Math.max(0, sceneTime - timing.offset) * timing.speed
    const current = evaluateSceneLayer(layer, localTime)
    const startOpacity = preset.start.opacity ?? 1
    const endOpacity = preset.end.opacity ?? startOpacity
    const startRotation = preset.start.rotation ?? 0
    const endRotation = preset.end.rotation ?? startRotation
    const endTime = localTime + preset.duration * timing.speed
    const end: SceneKeyframe = {
      id: uid(),
      time: endTime,
      x: current.x + preset.end.x - preset.start.x,
      y: current.y + preset.end.y - preset.start.y,
      scale: Math.max(.01, current.scale * preset.end.scale / Math.max(.01, preset.start.scale)),
      opacity: Math.max(0, Math.min(1, current.opacity + endOpacity - startOpacity)),
      rotation: current.rotation + endRotation - startRotation,
      curve: preset.curve,
    }
    const join: SceneKeyframe = { id: uid(), time: localTime, ...current, curve: preset.curve }
    const before = getSceneKeyframes(layer).filter(frame => frame.time < localTime - .000001)
    const frames = [...before, join, end]
    const duration = Math.max(layer.animation.duration, endTime)
    return withSceneKeyframes({
      ...layer,
      animation: {
        ...layer.animation,
        loop: false,
        trimEnd: duration,
      },
    }, frames, duration) as AnimatorLayer
  }
  const applyPreset = (presetId: string) => {
    if (!selected || selected.type === 'camera' || selected.locked) return
    const preset = PRESETS.find(item => item.id === presetId)
    if (!preset) return
    const target = scene.layers.find(layer => layer.id !== selected.id && layer.type === 'model3d' && !dependencyWouldCycle(selected.id, layer.id)) ?? scene.layers.find(layer => layer.id !== selected.id && isVisualLayer(layer) && !dependencyWouldCycle(selected.id, layer.id))
    if (preset.requiresTarget && !target) { setMessage('Add a second layer before applying this relational movement.'); return }
    if (chainFromPlayhead && !preset.requiresTarget) {
      const sceneTime = Math.round(progress * scene.duration * fps) / fps
      const nextDuration = Math.max(scene.duration, sceneTime + preset.duration)
      updateLayer(selected.id, layer => appendPresetAtPlayhead(layer, preset))
      updateScene(current => ({ ...current, duration: Math.max(current.duration, sceneTime + preset.duration) }))
      setProgress(sceneTime / nextDuration); setSelectedPresetId(preset.id); setSelectedKeyframeId(null); setMessage(`${preset.label} chained from frame ${Math.round(sceneTime * fps)} without a position jump.`)
      return
    }
    updateLayer(selected.id, layer => ({ ...layer, relationship: preset.requiresTarget ? undefined : layer.relationship, animation: { start: preset.start, end: preset.end, duration: preset.duration, curve: preset.curve, events: normalizeSceneEvents(layer.animation.events, preset.duration, layer.id), spin: preset.spin, rotationSpeed: layer.animation.rotationSpeed, clip: layer.animation.clip, clipOffset: layer.animation.clipOffset, clipSpeed: layer.animation.clipSpeed, clipReverse: layer.animation.clipReverse, clipLoop: layer.animation.clipLoop, clipTrimStart: layer.animation.clipTrimStart, clipTrimEnd: layer.animation.clipTrimEnd, orbit: preset.requiresTarget && target ? { targetLayerId: target.id, radiusX: 18, radiusY: 9, turns: 2, phase: 0, count: 1, facing: 'fixed', centerOffsetX: 0, centerOffsetY: 0 } : undefined } }))
    updateScene(current => ({ ...current, duration: Math.max(current.duration, preset.duration) }))
    setMessage(preset.requiresTarget ? `Orbit target: ${target?.name}` : null); setSelectedKeyframeId(null); setProgress(0)
  }
  const applyCameraPreset = (presetId: string) => {
    if (!selected || selected.type !== 'camera' || selected.locked) return
    const preset = CAMERA_PRESETS.find(item => item.id === presetId)
    if (!preset) return
    if (chainFromPlayhead) {
      const sceneTime = Math.round(progress * scene.duration * fps) / fps
      const nextDuration = Math.max(scene.duration, sceneTime + preset.duration)
      updateLayer(selected.id, layer => {
        const chained = appendPresetAtPlayhead(layer, preset)
        const timing = getSceneLayerTiming(layer)
        const startTime = timing.trimStart + Math.max(0, sceneTime - timing.offset) * timing.speed
        return { ...chained, animation: { ...chained.animation, shake: preset.shake ? { ...preset.shake, startTime, endTime: startTime + preset.duration * timing.speed } : undefined } }
      })
      updateScene(current => ({ ...current, duration: Math.max(current.duration, sceneTime + preset.duration) }))
      setProgress(sceneTime / nextDuration); setSelectedPresetId(preset.id); setSelectedKeyframeId(null); setMessage(`${preset.label} camera move chained from frame ${Math.round(sceneTime * fps)}.`)
      return
    }
    updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, x: preset.start.x, y: preset.start.y, scale: preset.start.scale, rotation: preset.start.rotation ?? 0 }, animation: { ...layer.animation, start: { ...preset.start }, end: { ...preset.end }, keyframes: undefined, events: normalizeSceneEvents(layer.animation.events, preset.duration, layer.id), duration: preset.duration, curve: preset.curve, offset: 0, speed: 1, loop: false, trimStart: 0, trimEnd: preset.duration, shake: preset.shake, orbit: undefined } }))
    updateScene(current => ({ ...current, duration: Math.max(current.duration, preset.duration) }))
    setSelectedPresetId(preset.id); setSelectedKeyframeId(null); setProgress(0); setMessage(`${preset.label} applied to ${selected.name}.`)
  }
  const applyPhotoMotionPreset = (presetId: string) => {
    if (!selected || selected.type !== 'image' || selected.locked) return
    const preset = PHOTO_MOTION_PRESETS.find(item => item.id === presetId)
    if (!preset) return
    const photoId = selected.id
    updateScene(current => {
      const currentPhoto = current.layers.find(layer => layer.id === photoId)
      if (!currentPhoto || currentPhoto.type !== 'image' || currentPhoto.locked) return current
      const reusableCamera = current.layers.find(layer => layer.type === 'camera' && layer.visible && !layer.locked)
        ?? current.layers.find(layer => layer.type === 'camera' && !layer.locked)
      const cameraId = reusableCamera?.id ?? uid()
      const camera: AnimatorLayer = {
        ...(reusableCamera ?? {
          id: cameraId,
          name: '',
          type: 'camera',
          source: '',
          visible: true,
          z: 0,
          transform: { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 },
          animation: { start: makePoint(50, 50, 1), end: makePoint(50, 50, 1), duration: preset.duration, curve: preset.curve },
        }),
        name: `Photo camera · ${preset.label}`,
        visible: true,
        relationship: undefined,
        transform: { x: preset.start.x, y: preset.start.y, scale: preset.start.scale, opacity: 1, rotation: preset.start.rotation ?? 0 },
        animation: {
          start: { ...preset.start },
          end: { ...preset.end },
          duration: preset.duration,
          curve: preset.curve,
          offset: 0,
          speed: 1,
          loop: false,
          trimStart: 0,
          trimEnd: preset.duration,
          shake: preset.shake,
        },
      }
      const photo: AnimatorLayer = {
        ...currentPhoto,
        fill: true,
        parallax: 1,
        transform: { ...currentPhoto.transform, x: 50, y: 50, scale: 1.2, opacity: 1, rotation: 0 },
        animation: {
          ...currentPhoto.animation,
          start: { x: 50, y: 50, scale: 1.2, opacity: 1, rotation: 0 },
          end: { x: 50, y: 50, scale: 1.2, opacity: 1, rotation: 0 },
          keyframes: undefined,
          duration: preset.duration,
          curve: 'linear',
          offset: 0,
          speed: 1,
          loop: false,
          trimStart: 0,
          trimEnd: preset.duration,
          orbit: undefined,
        },
      }
      const remaining = normalizeZ(current.layers
        .filter(layer => layer.id !== photoId && layer.id !== cameraId)
        .map(layer => layer.type === 'camera' && !layer.locked ? { ...layer, visible: false } : layer))
      return { ...current, duration: preset.duration, layers: assignZ([photo, ...remaining, camera]) }
    })
    setSelectedPresetId(preset.id)
    setSelectedKeyframeId(null)
    setSelectedEventId(null)
    setProgress(0)
    setMessage(`${preset.label} prepared as a ${preset.duration}s cinematic photo shot.`)
  }
  const confirmPresetRemoval = () => window.confirm('Remove this effect?')
  const removeLayerMotionPreset = () => {
    if (!selected || selected.locked || !confirmPresetRemoval()) return
    const point = {
      x: selected.transform.x,
      y: selected.transform.y,
      scale: selected.transform.scale,
      opacity: selected.transform.opacity,
      rotation: selected.transform.rotation ?? 0,
    }
    updateLayer(selected.id, layer => ({
      ...layer,
      relationship: undefined,
      animation: {
        ...layer.animation,
        start: { ...point },
        end: { ...point },
        keyframes: undefined,
        offset: 0,
        speed: 1,
        loop: false,
        trimStart: 0,
        trimEnd: layer.animation.duration,
        spin: false,
        orbit: undefined,
        shake: undefined,
      },
    }))
    setSelectedPresetId('')
    setSelectedKeyframeId(null)
    setProgress(0)
    setMessage(`Removed the motion effect from ${selected.name}.`)
  }
  const removePhotoMotionPreset = (presetId: string) => {
    if (!selected || selected.type !== 'image' || selected.locked || !confirmPresetRemoval()) return
    const preset = PHOTO_MOTION_PRESETS.find(item => item.id === presetId)
    if (!preset) return
    const photoId = selected.id
    updateScene(current => ({
      ...current,
      layers: current.layers
        .filter(layer => !(layer.type === 'camera' && layer.name === `Photo camera · ${preset.label}`))
        .map(layer => layer.id === photoId ? {
          ...layer,
          animation: {
            ...layer.animation,
            start: { x: layer.transform.x, y: layer.transform.y, scale: layer.transform.scale, opacity: layer.transform.opacity, rotation: layer.transform.rotation ?? 0 },
            end: { x: layer.transform.x, y: layer.transform.y, scale: layer.transform.scale, opacity: layer.transform.opacity, rotation: layer.transform.rotation ?? 0 },
            keyframes: undefined,
            offset: 0,
            speed: 1,
            loop: false,
            trimStart: 0,
            trimEnd: layer.animation.duration,
            orbit: undefined,
          },
        } : layer),
    }))
    setSelectedPresetId('')
    setSelectedKeyframeId(null)
    setProgress(0)
    setMessage(`Removed ${preset.label} from ${selected.name}.`)
  }
  const updateCameraTransform = (id: string, field: 'x' | 'y' | 'scale' | 'rotation', value: number) => updateLayer(id, layer => {
    if (layer.type !== 'camera') return layer
    const previous = field === 'rotation' ? layer.transform.rotation ?? 0 : layer.transform[field]
    if (field === 'scale') {
      const ratio = value / Math.max(.05, previous)
      return {
        ...layer,
        transform: { ...layer.transform, scale: value },
        animation: mapSceneAnimationPoints(layer, point => ({ ...point, scale: Math.max(.05, point.scale * ratio) })),
      }
    }
    const delta = value - previous
    return {
      ...layer,
      transform: { ...layer.transform, [field]: value },
      animation: mapSceneAnimationPoints(layer, point => ({ ...point, [field]: point[field] + delta })),
    }
  })
  const applyParallaxPreset = (id: string, preset: ParallaxPreset) => updateLayer(id, layer => {
    if (!isVisualLayer(layer)) return layer
    const parallax = PARALLAX_PRESETS[preset]
    if (preset !== 'background' || layer.type === 'model3d') return { ...layer, parallax }
    const overscan = 1.2
    return {
      ...layer,
      parallax,
      fill: true,
      transform: { ...layer.transform, scale: Math.max(overscan, layer.transform.scale) },
      animation: mapSceneAnimationPoints(layer, point => ({ ...point, scale: Math.max(overscan, point.scale) })),
    }
  })
  const dependencyWouldCycle = (layerId: string, targetId: string) => dependencyWouldCycleIn(scene.layers, layerId, targetId)
  const setLayerRelationship = (type: NonNullable<AnimatorLayer['relationship']>['type'] | 'none') => {
    if (!selected || selected.locked) return
    if (type === 'none') { updateLayer(selected.id, layer => ({ ...layer, relationship: undefined })); return }
    const existingTarget = selected.relationship && scene.layers.find(layer => layer.id === selected.relationship?.targetLayerId && isVisualLayer(layer))
    const target = existingTarget ?? scene.layers.find(layer => layer.id !== selected.id && isVisualLayer(layer) && !dependencyWouldCycle(selected.id, layer.id))
    if (!target) { setMessage('Add another visual layer before creating a relationship.'); return }
    const selectedState = layerState(selected, progress, new Set(), false)
    const targetState = layerState(target, progress, new Set(), false)
    const facingAngle = Math.atan2((targetState.y - selectedState.y) * scene.height, (targetState.x - selectedState.x) * scene.width) * 180 / Math.PI
    updateLayer(selected.id, layer => ({
      ...layer,
      relationship: {
        type,
        targetLayerId: target.id,
        offsetX: selectedState.x - targetState.x,
        offsetY: selectedState.y - targetState.y,
        strength: 1,
        rotationOffset: type === 'lookAt' ? selectedState.rotation - facingAngle : 0,
      },
      animation: { ...layer.animation, orbit: undefined },
    }))
  }
  const setRelationshipTarget = (targetId: string) => {
    if (!selected?.relationship || selected.locked || dependencyWouldCycle(selected.id, targetId)) { setMessage('That relationship would create a cycle.'); return }
    const target = scene.layers.find(layer => layer.id === targetId && isVisualLayer(layer))
    if (!target) return
    const selectedState = layerState(selected, progress, new Set(), false)
    const targetState = layerState(target, progress, new Set(), false)
    const facingAngle = Math.atan2((targetState.y - selectedState.y) * scene.height, (targetState.x - selectedState.x) * scene.width) * 180 / Math.PI
    updateLayer(selected.id, layer => ({ ...layer, relationship: layer.relationship ? { ...layer.relationship, targetLayerId: targetId, offsetX: selectedState.x - targetState.x, offsetY: selectedState.y - targetState.y, rotationOffset: layer.relationship.type === 'lookAt' ? selectedState.rotation - facingAngle : layer.relationship.rotationOffset } : undefined }))
  }
  const setOrbitTarget = (targetId: string) => {
    if (!selected || !isVisualLayer(selected) || selected.locked) return
    if (dependencyWouldCycle(selected.id, targetId)) { setMessage('That orbit would create a dependency cycle.'); return }
    updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, targetLayerId: targetId } : undefined } }))
  }
  const updateLayerEffects = (id: string, patch: Partial<LayerEffects>) => updateLayer(id, layer => ({ ...layer, effects: normalizedEffects({ ...normalizedEffects(layer.effects), ...patch }) }))
  const motion = (layer: AnimatorLayer) => ({ start: layer.animation.start, end: layer.animation.end, keyframes: layer.animation.keyframes, events: getSceneEvents(layer), duration: layer.animation.duration, curve: layer.animation.curve, offset: layer.animation.offset, speed: layer.animation.speed, loop: layer.animation.loop, trimStart: layer.animation.trimStart, trimEnd: layer.animation.trimEnd, spin: layer.animation.spin, rotationSpeed: layer.animation.rotationSpeed, shake: layer.animation.shake, orbit: layer.animation.orbit })
  const applyMotion = (raw: unknown) => {
    if (!selected || selected.locked) throw new Error('Select an unlocked layer before applying movement JSON.')
    const updated = sanitizeSceneMotion(raw, selected, {
      isValidOrbitTarget: targetId => targetId !== selected.id && scene.layers.some(layer => layer.id === targetId && isVisualLayer(layer)) && !dependencyWouldCycle(selected.id, targetId),
    }) as AnimatorLayer
    updateLayer(selected.id, () => updated)
    const timing = getSceneLayerTiming(updated)
    updateScene(current => ({ ...current, duration: Math.max(current.duration, timing.offset + timing.span / timing.speed) }))
    setSelectedKeyframeId(null); setSelectedEventId(null); setProgress(0)
  }
  const addKeyframeAtPlayhead = () => {
    if (!selected || selected.locked) { setMessage('Unlock the layer before adding keyframes.'); return }
    const sceneTime = progress * scene.duration
    const time = sceneTimeToLayerTime(selected, sceneTime)
    const frames = getSceneKeyframes(selected)
    const existing = frames.find(frame => Math.abs(frame.time - time) < .025)
    if (existing) { setSelectedKeyframeId(existing.id); setSelectedEventId(null); return }
    const point = evaluateSceneLayer(selected, time)
    const keyframe: SceneKeyframe = { id: uid(), time, ...point, curve: selected.animation.curve }
    updateLayer(selected.id, layer => withSceneKeyframes(layer, [...getSceneKeyframes(layer), keyframe], Math.max(layer.animation.duration, time)) as AnimatorLayer)
    updateScene(current => ({ ...current, duration: Math.max(current.duration, time) }))
    setSelectedKeyframeId(keyframe.id); setSelectedEventId(null)
    setMessage(`Keyframe added at local ${time.toFixed(2)}s (scene ${sceneTime.toFixed(2)}s).`)
  }
  const updateTimelineKeyframe = (keyframeId: string, patch: Partial<Omit<SceneKeyframe, 'id'>>) => {
    if (!selected || selected.locked) return
    const snappedPatch = { ...patch, x: patch.x === undefined ? undefined : snapCoordinate(patch.x), y: patch.y === undefined ? undefined : snapCoordinate(patch.y) }
    updateLayer(selected.id, layer => {
      const frames = getSceneKeyframes(layer)
      const index = frames.findIndex(frame => frame.id === keyframeId)
      if (index < 0) return layer
      const previousTime = index > 0 ? frames[index - 1].time + .01 : frames[index].time
      const nextTime = index < frames.length - 1 ? frames[index + 1].time - .01 : frames[index].time
      const time = index === 0 || index === frames.length - 1 ? frames[index].time : Math.max(previousTime, Math.min(nextTime, snappedPatch.time ?? frames[index].time))
      const updated = frames.map(frame => frame.id === keyframeId ? { ...frame, ...snappedPatch, x: snappedPatch.x ?? frame.x, y: snappedPatch.y ?? frame.y, time } : frame)
      return withSceneKeyframes(layer, updated) as AnimatorLayer
    })
  }
  const deleteTimelineKeyframe = () => {
    if (!selected || selected.locked || !selectedKeyframeId) return
    const frames = getSceneKeyframes(selected)
    const index = frames.findIndex(frame => frame.id === selectedKeyframeId)
    if (index <= 0 || index >= frames.length - 1) return
    updateLayer(selected.id, layer => withSceneKeyframes(layer, getSceneKeyframes(layer).filter(frame => frame.id !== selectedKeyframeId)) as AnimatorLayer)
    setSelectedKeyframeId(null)
    setMessage('Keyframe deleted.')
  }
  const addEventAtPlayhead = () => {
    if (!selected || selected.locked) { setMessage('Unlock the layer before adding events.'); return }
    const sceneTime = progress * scene.duration
    const time = sceneTimeToLayerTime(selected, sceneTime)
    const event: SceneAnimationEvent = { id: uid(), time, name: `Event ${getSceneEvents(selected).length + 1}` }
    updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, events: [...getSceneEvents(layer), event].sort((a, b) => a.time - b.time) } }))
    setSelectedKeyframeId(null); setSelectedEventId(event.id)
    setMessage(`Event added at local ${time.toFixed(2)}s (scene ${sceneTime.toFixed(2)}s).`)
  }
  const updateTimelineEvent = (eventId: string, patch: Partial<Omit<SceneAnimationEvent, 'id'>>) => {
    if (!selected || selected.locked) return
    updateLayer(selected.id, layer => ({
      ...layer,
      animation: {
        ...layer.animation,
        events: getSceneEvents(layer).map(event => event.id === eventId ? {
          ...event,
          ...patch,
          time: Math.max(0, Math.min(layer.animation.duration, finiteNumber(patch.time, event.time))),
          name: patch.name === undefined ? event.name : patch.name.trim().slice(0, 100) || 'Event',
          payload: patch.payload === undefined ? event.payload : patch.payload.slice(0, 2000) || undefined,
        } : event).sort((a, b) => a.time - b.time),
      },
    }))
  }
  const deleteTimelineEvent = () => {
    if (!selected || selected.locked || !selectedEventId) return
    updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, events: getSceneEvents(layer).filter(event => event.id !== selectedEventId) } }))
    setSelectedEventId(null); setMessage('Animation event deleted.')
  }
  const copyTimelineKeyframes = () => {
    if (!selected) return
    const payload = JSON.stringify({ version: 1, keyframes: getSceneKeyframes(selected) }, null, 2)
    keyframeClipboardRef.current = payload
    void navigator.clipboard?.writeText(payload).catch(() => {})
    setMessage(`${getSceneKeyframes(selected).length} keyframes copied.`)
  }
  const pasteTimelineKeyframes = async () => {
    if (!selected || selected.locked) { setMessage('Unlock the target layer before pasting keyframes.'); return }
    let text = keyframeClipboardRef.current
    try { text = await navigator.clipboard?.readText() || text } catch { /* Internal clipboard remains available. */ }
    if (!text) { setMessage('Copy keyframes first.'); return }
    try {
      const parsed = JSON.parse(text) as { keyframes?: unknown }
      const frames = normalizeSceneKeyframes(Array.isArray(parsed) ? parsed : parsed.keyframes, selected)?.map(frame => ({ ...frame, id: uid() }))
      if (!frames) throw new Error('Clipboard does not contain at least two valid keyframes.')
      const pastedDuration = Math.max(.1, frames[frames.length - 1].time)
      updateLayer(selected.id, layer => withSceneKeyframes({ ...layer, animation: { ...layer.animation, trimStart: 0, trimEnd: pastedDuration } }, frames, pastedDuration) as AnimatorLayer)
      const timing = getSceneLayerTiming({ ...selected, animation: { ...selected.animation, duration: pastedDuration, trimStart: 0, trimEnd: pastedDuration } })
      const effectiveEnd = timing.offset + timing.span / timing.speed
      updateScene(current => ({ ...current, duration: Math.max(current.duration, effectiveEnd) }))
      setSelectedKeyframeId(frames[0].id); setSelectedEventId(null); setProgress(timing.offset / Math.max(.1, Math.max(scene.duration, effectiveEnd))); setMessage(`${frames.length} keyframes pasted.`)
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Invalid keyframe clipboard.') }
  }
  const exportScene = () => {
    try {
      const current = sceneRef.current
      const url = URL.createObjectURL(new Blob([serializeSceneFile(current)], { type: 'application/json;charset=utf-8' }))
      const link = document.createElement('a')
      link.href = url
      link.download = sceneFileName(current.name)
      link.rel = 'noopener'
      link.style.display = 'none'
      document.body.appendChild(link)
      link.click()
      window.setTimeout(() => { link.remove(); URL.revokeObjectURL(url) }, 1500)
      const localAssets = current.layers.filter(layer => layer.type !== 'camera' && layer.source.startsWith('blob:')).length
      setMessage(localAssets > 0 ? `Scene JSON exported. ${localAssets} local asset${localAssets === 1 ? '' : 's'} will require reassignment when imported.` : 'Scene JSON exported.')
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Scene JSON could not be exported.') }
  }
  const importScene = (text: string, successMessage?: string) => {
    try {
      const incoming = parseSceneFile(text) as AnimatorScene
      const incomingIds = incoming.layers.map((layer, index) => {
        const id = (layer as { id?: unknown } | null)?.id
        if (typeof id !== 'string' || !id.trim()) throw new Error(`Layer ${index + 1} needs a valid id.`)
        return id
      })
      if (new Set(incomingIds).size !== incomingIds.length) throw new Error('Every scene layer must have a unique id.')
      const width = Math.round(boundedNumber(incoming.width, 1280, 64, 7680))
      const height = Math.round(boundedNumber(incoming.height, 720, 64, 7680))
      const incomingVisualIds = new Set(incoming.layers.filter(layer => layer && layer.type !== 'camera').map(layer => layer.id))
      const activeCameraId = [...incoming.layers]
        .filter(layer => layer.type === 'camera' && layer.visible)
        .sort((a, b) => (b.z ?? 0) - (a.z ?? 0))[0]?.id
      const normalizedLayers = normalizeZ(incoming.layers.map(rawLayer => {
        if (!isAnimatorLayerType((rawLayer as { type?: unknown }).type)) throw new Error(`Unsupported scene layer type: ${String((rawLayer as { type?: unknown }).type ?? 'missing')}`)
        const isCamera = rawLayer.type === 'camera'
        const isModel = rawLayer.type === 'model3d'
        const isEffect = rawLayer.type === 'effect'
        const transform = {
          ...rawLayer.transform,
          x: finiteNumber(rawLayer.transform?.x, 50),
          y: finiteNumber(rawLayer.transform?.y, 50),
          scale: boundedNumber(rawLayer.transform?.scale, 1, .01, 20),
          opacity: boundedNumber(rawLayer.transform?.opacity, 1, 0, 1),
          rotation: finiteNumber(rawLayer.transform?.rotation, 0),
          rotationX: boundedNumber(rawLayer.transform?.rotationX, 75, 1, 179),
          rotationY: finiteNumber(rawLayer.transform?.rotationY, 0),
        }
        const start = { x: finiteNumber(rawLayer.animation?.start?.x, transform.x), y: finiteNumber(rawLayer.animation?.start?.y, transform.y), scale: boundedNumber(rawLayer.animation?.start?.scale, transform.scale, .01, 20), opacity: boundedNumber(rawLayer.animation?.start?.opacity, transform.opacity, 0, 1), rotation: finiteNumber(rawLayer.animation?.start?.rotation, transform.rotation) }
        const end = { x: finiteNumber(rawLayer.animation?.end?.x, transform.x), y: finiteNumber(rawLayer.animation?.end?.y, transform.y), scale: boundedNumber(rawLayer.animation?.end?.scale, transform.scale, .01, 20), opacity: boundedNumber(rawLayer.animation?.end?.opacity, transform.opacity, 0, 1), rotation: finiteNumber(rawLayer.animation?.end?.rotation, transform.rotation) }
        const visible = isCamera ? rawLayer.id === activeCameraId : rawLayer.visible !== false
        const rawRelationship = rawLayer.relationship
        const relationshipTypes = ['parent', 'follow', 'lookAt']
        const relationship = rawRelationship && relationshipTypes.includes(rawRelationship.type) && (!isCamera || rawRelationship.type === 'follow') && rawRelationship.targetLayerId !== rawLayer.id && incomingVisualIds.has(rawRelationship.targetLayerId) ? {
          type: rawRelationship.type,
          targetLayerId: rawRelationship.targetLayerId,
          offsetX: Number.isFinite(rawRelationship.offsetX) ? rawRelationship.offsetX : 0,
          offsetY: Number.isFinite(rawRelationship.offsetY) ? rawRelationship.offsetY : 0,
          strength: Number.isFinite(rawRelationship.strength) ? Math.max(0, Math.min(1, rawRelationship.strength ?? 1)) : 1,
          rotationOffset: Number.isFinite(rawRelationship.rotationOffset) ? rawRelationship.rotationOffset : 0,
        } as AnimatorLayer['relationship'] : undefined
        const rawShake = rawLayer.animation?.shake
        const shake = isCamera && rawShake && Number.isFinite(rawShake.amount) && Number.isFinite(rawShake.frequency) ? { amount: Math.max(0, Math.min(8, rawShake.amount)), frequency: Math.max(.1, Math.min(30, rawShake.frequency)), seed: Number.isFinite(rawShake.seed) ? rawShake.seed : 0, startTime: typeof rawShake.startTime === 'number' && Number.isFinite(rawShake.startTime) ? Math.max(0, Math.min(3600, rawShake.startTime)) : undefined, endTime: typeof rawShake.endTime === 'number' && Number.isFinite(rawShake.endTime) ? Math.max(0, Math.min(3600, rawShake.endTime)) : undefined } : undefined
        const rawOrbit = rawLayer.animation?.orbit
        const orbit = !isCamera && rawOrbit && rawOrbit.targetLayerId !== rawLayer.id && incomingVisualIds.has(rawOrbit.targetLayerId) ? {
          targetLayerId: rawOrbit.targetLayerId,
          radiusX: boundedNumber(rawOrbit.radiusX, 18, 0, 100),
          radiusY: boundedNumber(rawOrbit.radiusY, 9, 0, 100),
          turns: boundedNumber(rawOrbit.turns, 1, -20, 20),
          phase: boundedNumber(rawOrbit.phase, 0, -360, 360),
          count: Math.round(boundedNumber(rawOrbit.count, 1, 1, 12)),
          facing: ['fixed', 'center', 'outward'].includes(rawOrbit.facing ?? '') ? rawOrbit.facing as 'fixed' | 'center' | 'outward' : 'fixed',
          centerOffsetX: boundedNumber(rawOrbit.centerOffsetX, 0, -100, 100),
          centerOffsetY: boundedNumber(rawOrbit.centerOffsetY, 0, -100, 100),
        } : undefined
        const duration = boundedNumber(rawLayer.animation?.duration, finiteNumber(incoming.duration, 5), .1, 3600)
        const curve: SceneCurve = ['linear', 'ease', 'dramatic', 'bounce', 'hold'].includes(rawLayer.animation?.curve ?? '') ? rawLayer.animation.curve : 'linear'
        const events = normalizeSceneEvents(rawLayer.animation?.events, duration, rawLayer.id)
        const clip = isModel && typeof rawLayer.animation?.clip === 'string' && rawLayer.animation.clip.trim() ? rawLayer.animation.clip.trim().slice(0, 200) : undefined
        const clipOffset = isModel ? boundedNumber(rawLayer.animation?.clipOffset, 0, 0, 3600) : undefined
        const clipSpeed = isModel ? boundedNumber(rawLayer.animation?.clipSpeed, 1, .05, 8) : undefined
        const clipTrimStart = isModel ? boundedNumber(rawLayer.animation?.clipTrimStart, 0, 0, 3600) : undefined
        const clipTrimEnd = isModel && typeof rawLayer.animation?.clipTrimEnd === 'number' && Number.isFinite(rawLayer.animation.clipTrimEnd) ? Math.max((clipTrimStart ?? 0) + .001, Math.min(3600, rawLayer.animation.clipTrimEnd)) : undefined
        const layer = {
          ...rawLayer,
          name: typeof rawLayer.name === 'string' && rawLayer.name.trim() ? rawLayer.name : `Layer ${rawLayer.id}`,
          source: isCamera ? '' : String(rawLayer.source ?? ''),
          visible,
          locked: rawLayer.locked === true,
          relationship,
          effects: isCamera ? undefined : normalizedEffects(rawLayer.effects),
          strip: isCamera ? undefined : normalizedStrip(rawLayer.strip),
          atmosphere: isEffect ? normalizedAtmosphere(rawLayer.atmosphere) : undefined,
          parallax: isCamera ? undefined : typeof rawLayer.parallax === 'number' && Number.isFinite(rawLayer.parallax) ? Math.max(0, Math.min(2, rawLayer.parallax)) : 1,
          transform,
          animation: { ...rawLayer.animation, start, end, keyframes: undefined, events, duration, curve, clip, clipOffset, clipSpeed, clipReverse: isModel ? rawLayer.animation?.clipReverse === true : undefined, clipLoop: isModel ? rawLayer.animation?.clipLoop !== false : undefined, clipTrimStart, clipTrimEnd, shake, orbit },
          missingAsset: isCamera || isEffect ? false : Boolean(rawLayer.missingAsset || !String(rawLayer.source ?? '').trim() || isMissing(String(rawLayer.source ?? ''))),
        } as AnimatorLayer
        const timedLayer = withNormalizedSceneTiming(layer) as AnimatorLayer
        const keyframes = normalizeSceneKeyframes(rawLayer.animation?.keyframes, timedLayer)
        return keyframes ? withSceneKeyframes(timedLayer, keyframes, timedLayer.animation.duration) as AnimatorLayer : timedLayer
      }))
      const layers = breakDependencyCycles(normalizedLayers)
      const duration = Math.min(3600, Math.max(.1, Number.isFinite(incoming.duration) ? incoming.duration : 5, ...layers.map(layer => { const timing = getSceneLayerTiming(layer); return timing.offset + timing.span / timing.speed })))
      const incomingComposition = incoming.composition as Partial<NonNullable<Scene['composition']>> | undefined
      const safeAreas: NonNullable<Scene['composition']>['safeArea'][] = ['none', 'action', 'title', 'vertical', 'all']
      const rawGridSize = typeof incomingComposition?.gridSize === 'number' && Number.isFinite(incomingComposition.gridSize) ? incomingComposition.gridSize : DEFAULT_COMPOSITION.gridSize
      const composition: NonNullable<Scene['composition']> = {
        showGrid: incomingComposition?.showGrid === true,
        gridSize: Math.max(1, Math.min(50, rawGridSize)),
        snap: incomingComposition?.snap === true,
        safeArea: safeAreas.includes(incomingComposition?.safeArea as NonNullable<Scene['composition']>['safeArea']) ? incomingComposition?.safeArea as NonNullable<Scene['composition']>['safeArea'] : 'none',
      }
      const previousObjectUrls = new Set(sceneRef.current.layers.flatMap(layer => [layer.source, layer.thumbnail].filter((value): value is string => Boolean(value?.startsWith('blob:')))))
      previousObjectUrls.forEach(url => URL.revokeObjectURL(url))
      const missingAssets = layers.filter(layer => layer.type !== 'camera' && layer.missingAsset).length
      localFilesRef.current = {}; pastScenesRef.current = []; futureScenesRef.current = []; lastHistoryAtRef.current = 0; replaceScene({ ...blankScene(), ...incoming, name: typeof incoming.name === 'string' && incoming.name.trim() ? incoming.name : 'Imported scene', width, height, fps: incoming.fps === 60 ? 60 : 30, duration, layers, composition }); setHistoryRevision(value => value + 1); setSelectedId(layers[0]?.id ?? null); setSelectedKeyframeId(null); setSelectedEventId(null); setProgress(0); setMessage(successMessage ?? `Scene imported: ${layers.length} layer${layers.length === 1 ? '' : 's'}.${missingAssets ? ` Reassign ${missingAssets} missing asset${missingAssets === 1 ? '' : 's'}.` : ''}`); setJsonOpen(false)
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Invalid scene JSON.') }
  }
  const importSceneFile = async (file: File) => {
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error('Scene JSON is unexpectedly large (maximum 20 MB).')
      importScene(await file.text())
    } catch (error) { setMessage(error instanceof Error ? error.message : 'The scene file could not be read.') }
  }
  const loadMotionFile = async (file: File) => {
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error('Movement JSON is unexpectedly large (maximum 2 MB).')
      setMotionText((await file.text()).replace(/^\uFEFF/, '').trim())
      setMessage(`Movement JSON loaded from ${file.name}.`)
    } catch (error) { setMessage(error instanceof Error ? error.message : 'The movement file could not be read.') }
  }
  useEffect(() => {
    const pending = sessionStorage.getItem(PENDING_SCENE_KEY)
    if (pending) {
      sessionStorage.removeItem(PENDING_SCENE_KEY)
      importScene(pending)
      return
    }
    const autosave = localStorage.getItem(AUTOSAVE_KEY)
    if (!autosave) return
    try {
      const parsed = JSON.parse(autosave) as Partial<AnimatorScene>
      if (parsed.version === 1 && Array.isArray(parsed.layers) && parsed.layers.length > 0) {
        importScene(autosave)
        setMessage('Autosave restored. Local assets may need reassignment.')
      }
    } catch { localStorage.removeItem(AUTOSAVE_KEY) }
    // Scene restoration is intentionally a one-time mount operation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    if (!scene.layers.length) return
    const timer = window.setTimeout(() => {
      try {
        localStorage.setItem(AUTOSAVE_KEY, serializeSceneFile(scene))
        setLastAutosaveAt(Date.now())
      } catch {
        setMessage('Autosave could not be written in this browser.')
      }
    }, 700)
    return () => window.clearTimeout(timer)
  }, [scene])
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return
      const target = event.target as HTMLElement | null
      if (target?.matches('input, textarea, select, [contenteditable="true"]')) return
      const key = event.key.toLowerCase()
      if (key === 's') {
        event.preventDefault()
        void persistScene()
        return
      }
      if (key !== 'z') return
      event.preventDefault()
      if (event.shiftKey) redoScene(); else undoScene()
    }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
    // Rebind when history changes so keyboard state and buttons stay aligned.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyRevision])
  const paintScene = (canvas: HTMLCanvasElement, progress: number, exportModelCanvases?: Map<string, HTMLCanvasElement[]>) => {
    const current = sceneRef.current
    const sceneProgress = Math.max(0, Math.min(1, progress))
    const sceneSeconds = sceneProgress * current.duration
    const context = canvas.getContext('2d')
    if (!context) return false
    context.fillStyle = '#0b1020'; context.fillRect(0, 0, canvas.width, canvas.height)
    current.layers
      .filter(layer => layer.visible && isVisualLayer(layer))
      .flatMap(layer => renderedLayerStates(layer, sceneProgress).map((state, instanceIndex) => ({ layer, state, instanceIndex })))
      .sort((a, b) => a.state.z - b.state.z)
      .forEach(({ layer, state, instanceIndex }) => {
      const effects = normalizedEffects(layer.effects)
      context.save(); context.globalAlpha = state.opacity
      context.globalCompositeOperation = effects.blendMode === 'normal' ? 'source-over' : effects.blendMode
      if ('filter' in context) context.filter = effectFilter(effects, Math.min(canvas.width, canvas.height) / 100)
      const width = canvas.width * (layer.type === 'model3d' ? .52 : 1) * state.scale
      const height = canvas.height * (layer.type === 'model3d' ? .75 : 1) * state.scale
      context.translate(canvas.width * state.x / 100, canvas.height * state.y / 100); context.rotate(state.rotation * Math.PI / 180)
      applyLayerMask(context, effects, width, height)
      if (layer.type === 'effect') {
        drawAtmosphere(context, normalizedAtmosphere(layer.atmosphere), sceneSeconds, width, height)
      } else if (layer.type === 'model3d') {
        const viewer = exportModelCanvases?.get(layer.id)?.[instanceIndex]
          ?? modelViewerCanvas(findLayerElements(canvasRef.current, layer.id)[instanceIndex] ?? null)
        if (viewer) context.drawImage(viewer, -width / 2, -height / 2, width, height)
      } else {
        const media = findLayerElement(canvasRef.current, layer.id) as HTMLVideoElement | HTMLImageElement | null
        if (media && (media instanceof HTMLVideoElement ? media.readyState >= 2 : media.complete)) {
          const sourceWidth = media instanceof HTMLVideoElement ? media.videoWidth : media.naturalWidth
          const sourceHeight = media instanceof HTMLVideoElement ? media.videoHeight : media.naturalHeight
          const sourceRatio = sourceWidth / Math.max(1, sourceHeight); const targetRatio = width / Math.max(1, height)
          let drawWidth = width; let drawHeight = height
          if (!layer.fill) { if (sourceRatio > targetRatio) drawHeight = width / sourceRatio; else drawWidth = height * sourceRatio }
          else if (sourceRatio > targetRatio) drawWidth = height * sourceRatio; else drawHeight = width / sourceRatio
          context.beginPath(); context.rect(-width / 2, -height / 2, width, height); context.clip()
          context.drawImage(media, -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight)
        }
      }
      context.restore()
    })
    current.layers
      .filter(layer => layer.visible && isVisualLayer(layer) && normalizedStrip(layer.strip).seamOccluder.enabled)
      .forEach(layer => {
        const kind = normalizedStrip(layer.strip).seamOccluder.kind
        seamCoverStates(layer, sceneProgress).forEach(state => {
          context.save()
          context.globalAlpha = state.opacity
          context.translate(canvas.width * state.x / 100, canvas.height * state.y / 100)
          context.rotate(state.rotation * Math.PI / 180)
          paintSeamOccluder(context, kind, canvas.width, canvas.height, normalizedStrip(layer.strip).seamOccluder.scale)
          context.restore()
        })
      })
    return true
  }
  // Compatibility fallback for browsers without WebCodecs. Chromium uses the
  // deterministic MP4 path below so slow WebGL frames never change timing.
  const recordCompatibilityWebm = (): Promise<Blob> => new Promise((resolve, reject) => {
    if (recording) { reject(new Error('A recording is already in progress.')); return }
    if (playing) { const error = new Error('Wait for Preview to finish before recording.'); setMessage(error.message); reject(error); return }
    const current = sceneRef.current
    const currentFps: SceneFrameRate = current.fps === 60 ? 60 : 30
    if (!current.layers.some(layer => layer.visible && isVisualLayer(layer))) { const error = new Error('Add a visible visual layer before recording.'); setMessage(error.message); reject(error); return }
    if (!('MediaRecorder' in window)) { const error = new Error('This browser cannot record the scene.'); setMessage(error.message); reject(error); return }
    const canvas = document.createElement('canvas'); canvas.width = current.width; canvas.height = current.height; const context = canvas.getContext('2d'); if (!context) { reject(new Error('Could not create a recording canvas.')); return }
    if (!('filter' in context) && current.layers.some(layer => isVisualLayer(layer) && hasCanvasFilterEffects(normalizedEffects(layer.effects)))) { const error = new Error('This browser can preview layer filters but cannot capture them. Use Chromium/Chrome to record this scene.'); setMessage(error.message); reject(error); return }
    let stream: MediaStream | null = null
    let recorder: MediaRecorder | null = null
    const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9') ? 'video/webm;codecs=vp9' : 'video/webm'
    const videoBitsPerSecond = Math.round(Math.max(4_000_000, Math.min(60_000_000, current.width * current.height * currentFps * .12)))
    try {
      stream = canvas.captureStream(currentFps)
      recorder = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond })
    } catch (error) {
      stream?.getTracks().forEach(track => track.stop())
      const message = error instanceof Error ? `Recording could not start: ${error.message}` : 'Recording could not start in this browser.'
      setMessage(message)
      reject(new Error(message))
      return
    }
    const captureStream = stream
    const mediaRecorder = recorder
    const chunks: Blob[] = []
    let failed = false
    let finishing = false
    const clearCapture = () => {
      if (recordingAnimationRef.current !== null) cancelAnimationFrame(recordingAnimationRef.current)
      recordingAnimationRef.current = null
      if (mediaRecorderRef.current === mediaRecorder) mediaRecorderRef.current = null
      if (recordingStreamRef.current === captureStream) recordingStreamRef.current = null
      captureStream.getTracks().forEach(track => track.stop())
      Object.values(videoRefs.current).forEach(video => video?.pause())
      setRecording(false)
    }
    const fail = (error: unknown) => {
      if (failed) return
      failed = true
      const detail = error instanceof Error ? error.message : String(error || 'Unknown recorder error')
      setMessage(`Recording failed: ${detail}`)
      if (mediaRecorder.state !== 'inactive') {
        try { mediaRecorder.stop() } catch { clearCapture() }
      } else clearCapture()
      reject(error instanceof Error ? error : new Error(detail))
    }
    mediaRecorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
    mediaRecorder.onerror = event => fail((event as Event & { error?: DOMException }).error ?? new Error('MediaRecorder reported an error.'))
    mediaRecorder.onstop = () => {
      if (!failed && chunks.length > 0) {
        const blob = new Blob(chunks, { type: mime })
        clearCapture()
        resolve(blob)
        return
      }
      clearCapture()
      if (!failed) {
        const error = new Error('Recording stopped without producing video data.')
        setMessage(error.message)
        reject(error)
      }
    }
    mediaRecorderRef.current = mediaRecorder
    recordingStreamRef.current = captureStream
    resetSceneMedia(); setRecording(true); setProgress(0); setMessage(null)
    recordingAnimationRef.current = requestAnimationFrame(() => {
      try {
        paintScene(canvas, 0)
        mediaRecorder.start(250)
      } catch (error) { fail(error); return }
      const started = performance.now(); let syncedFrame = 0
      const finish = () => {
        if (finishing) return
        finishing = true
        try {
          const readyProgress = Math.min(1, syncedFrame / currentFps / current.duration)
          setProgress(readyProgress); paintScene(canvas, readyProgress)
          syncSceneMedia(current.duration)
          recordingAnimationRef.current = requestAnimationFrame(() => {
            try {
              setProgress(1); paintScene(canvas, 1)
              if (mediaRecorder.state !== 'inactive') mediaRecorder.stop(); else clearCapture()
            } catch (error) { fail(error) }
          })
        } catch (error) { fail(error) }
      }
      const frame = (now: number) => {
        try {
          const elapsed = Math.min(current.duration, (now - started) / 1000)
          if (elapsed >= current.duration) { finish(); return }
          const desiredFrame = Math.floor(elapsed * currentFps)
          if (desiredFrame !== syncedFrame) {
            const readyProgress = Math.min(1, syncedFrame / currentFps / current.duration)
            setProgress(readyProgress); paintScene(canvas, readyProgress)
            syncedFrame = desiredFrame
            syncSceneMedia(Math.min(current.duration, desiredFrame / currentFps))
          }
          recordingAnimationRef.current = requestAnimationFrame(frame)
        } catch (error) { fail(error) }
      }
      recordingAnimationRef.current = requestAnimationFrame(frame)
    })
  })
  const nextPaint = () => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))

  const createExportModelStage = async (current: AnimatorScene) => {
    const host = document.createElement('div')
    // model-viewer renders at its CSS size. Keep a separate, almost invisible
    // stage at the final output size instead of upscaling the small editor
    // preview canvas into the recording.
    host.style.cssText = 'position:fixed;left:0;top:0;z-index:-1;display:flex;flex-wrap:wrap;gap:1px;opacity:.001;pointer-events:none;contain:layout style paint;'
    document.body.append(host)
    const viewers = new Map<string, ModelViewerAnimationElement[]>()
    const canvases = new Map<string, HTMLCanvasElement[]>()
    const models = current.layers.filter((layer): layer is VisualAnimatorLayer => layer.visible && layer.type === 'model3d' && !layer.missingAsset && Boolean(layer.source))

    for (const layer of models) {
      const scales = [layer.transform.scale, layer.animation.start.scale, layer.animation.end.scale, ...getSceneKeyframes(layer).map(frame => frame.scale)]
      const maxScale = Math.max(.01, ...scales)
      const instanceCount = Math.max(1, renderedLayerStates(layer, 0).length)
      const width = Math.min(4096, Math.max(64, Math.ceil(current.width * .52 * maxScale)))
      const height = Math.min(4096, Math.max(64, Math.ceil(current.height * .75 * maxScale)))
      const entries: ModelViewerAnimationElement[] = []
      for (let index = 0; index < instanceCount; index += 1) {
        const viewer = document.createElement('model-viewer') as ModelViewerAnimationElement
        viewer.setAttribute('src', layer.source)
        viewer.setAttribute('camera-orbit', `${layer.transform.rotationY ?? 0}deg ${layer.transform.rotationX ?? 75}deg auto`)
        viewer.setAttribute('orientation', '0deg 0deg 0deg')
        viewer.setAttribute('interaction-prompt', 'none')
        viewer.setAttribute('shadow-intensity', '1')
        viewer.setAttribute('exposure', '1')
        viewer.style.cssText = `display:block;width:${width}px;height:${height}px;`
        host.append(viewer)
        entries.push(viewer)
      }
      viewers.set(layer.id, entries)
    }

    const deadline = Date.now() + 30000
    while (Date.now() < deadline) {
      let ready = true
      for (const entries of viewers.values()) {
        for (const viewer of entries) {
          const canvas = modelViewerCanvas(viewer)
          if (viewer.loaded !== true || !canvas || canvas.width < 64 || canvas.height < 64) { ready = false; break }
        }
        if (!ready) break
      }
      if (ready) break
      await new Promise(resolve => window.setTimeout(resolve, 80))
    }
    for (const [id, entries] of viewers) {
      const rendered = entries.map(viewer => modelViewerCanvas(viewer)).filter((canvas): canvas is HTMLCanvasElement => Boolean(canvas))
      if (rendered.length !== entries.length) {
        host.remove()
        throw new Error('The high-resolution 3D export stage did not paint in time.')
      }
      canvases.set(id, rendered)
    }
    await nextPaint()

    return {
      canvases,
      async renderFrame(progress: number) {
        for (const layer of models) {
          const entries = viewers.get(layer.id) ?? []
          const states = renderedLayerStates(layer, progress)
          entries.forEach((viewer, index) => {
            const state = states[index] ?? states[0]
            viewer.setAttribute('orientation', `0deg ${state?.modelYaw ?? 0}deg 0deg`)
            if (layer.animation.clip) {
              viewer.setAttribute('animation-name', layer.animation.clip)
              const clipTime = getSceneClipTime(layer, progress * current.duration, Math.max(.001, viewer.duration || 0))
              viewer.currentTime = clipTime
              viewer.pause()
            }
          })
        }
        // WebGL updates asynchronously after orientation/currentTime changes.
        // Two presentation cycles ensure the copied canvas is the requested frame.
        await nextPaint()
      },
      dispose() { host.remove() },
    }
  }

  const recordToBlob = async (): Promise<Blob> => {
    if (recording) throw new Error('A recording is already in progress.')
    if (playing) throw new Error('Wait for Preview to finish before recording.')
    if (!('VideoEncoder' in window) || typeof VideoEncoder.isConfigSupported !== 'function') {
      setMessage('This browser lacks deterministic WebCodecs export; using compatibility recording.')
      return recordCompatibilityWebm()
    }
    const current = sceneRef.current
    const fps: SceneFrameRate = current.fps === 60 ? 60 : 30
    if (!current.layers.some(layer => layer.visible && isVisualLayer(layer))) throw new Error('Add a visible visual layer before recording.')
    const canvas = document.createElement('canvas')
    canvas.width = current.width
    canvas.height = current.height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Could not create a recording canvas.')
    if (!('filter' in context) && current.layers.some(layer => isVisualLayer(layer) && hasCanvasFilterEffects(normalizedEffects(layer.effects)))) {
      throw new Error('This browser cannot render the scene filters at export quality. Use Chromium/Chrome to record this scene.')
    }

    const frameDurationUs = Math.round(1_000_000 / fps)
    const frameCount = Math.max(1, Math.round(current.duration * fps))
    const bitrate = Math.round(Math.max(8_000_000, Math.min(80_000_000, current.width * current.height * fps * .22)))
    const supported = await VideoEncoder.isConfigSupported({ codec: 'avc1.640028', width: current.width, height: current.height, bitrate, framerate: fps, avc: { format: 'avc' } })
    if (!supported.supported || !supported.config) {
      throw new Error('This browser cannot encode a deterministic H.264 MP4 at the selected resolution.')
    }

    const target = new ArrayBufferTarget()
    const muxer = new Muxer({
      target,
      video: { codec: 'avc', width: current.width, height: current.height, frameRate: fps },
      fastStart: 'in-memory',
      firstTimestampBehavior: 'strict',
    })
    let encoderError: Error | null = null
    const encoder = new VideoEncoder({
      output: (chunk, metadata) => muxer.addVideoChunk(chunk, metadata),
      error: error => { encoderError = error instanceof Error ? error : new Error(String(error)) },
    })
    encoder.configure(supported.config)
    const exportStage = await createExportModelStage(current)
    try {
      resetSceneMedia()
      setRecording(true)
      setProgress(0)
      setMessage(`Rendering ${frameCount} exact frames at ${fps} FPS…`)
      for (let index = 0; index < frameCount; index += 1) {
        if (encoderError) throw encoderError
        const seconds = Math.min(current.duration, index / fps)
        const progress = sceneProgressFromSeconds(seconds, current.duration)
        syncSceneMedia(seconds)
        await exportStage.renderFrame(progress)
        if (!paintScene(canvas, progress, exportStage.canvases)) throw new Error('Could not paint export frame.')
        const frame = new VideoFrame(canvas, { timestamp: index * frameDurationUs, duration: frameDurationUs })
        encoder.encode(frame, { keyFrame: index % Math.max(1, fps * 2) === 0 })
        frame.close()
        if (encoder.encodeQueueSize > 8) await encoder.flush()
        setProgress((index + 1) / frameCount)
      }
      await encoder.flush()
      if (encoderError) throw encoderError
      muxer.finalize()
      return new Blob([target.buffer], { type: 'video/mp4' })
    } finally {
      encoder.close()
      exportStage.dispose()
      Object.values(videoRefs.current).forEach(video => video?.pause())
      setRecording(false)
    }
  }

  const publishRecording = async (blob: Blob, current: Scene) => {
    const context = recipeContextRef.current
    const saved = await saveSceneRecording(blob, {
      scene: current,
      prompt: context?.prompt ?? '',
      recipe: context ? context.recipe as unknown as Record<string, unknown> : null,
      workspace,
    })
    await loadOutputs()
    setMessage(`MP4 saved in Videos as ${saved.name}`)
    return saved
  }
  const record = () => {
    if (publishing) return
    setPublishing(true)
    setMessage(null)
    void waitForModelViewers()
      .then(() => recordToBlob())
      .then(blob => publishRecording(blob, sceneRef.current))
      .catch(error => setMessage(error instanceof Error ? error.message : 'Failed to export MP4.'))
      .finally(() => setPublishing(false))
  }
  const waitForModelViewers = async () => {
    const root = canvasRef.current
    if (!root) return
    const deadline = Date.now() + 25000
    const expectedModelIds = new Set(
      sceneRef.current.layers
        .filter(layer => layer.type === 'model3d' && layer.visible && !layer.missingAsset && layer.source)
        .map(layer => layer.id),
    )
    if (!expectedModelIds.size) return
    while (Date.now() < deadline) {
      const viewers = [...root.querySelectorAll<ModelViewerAnimationElement>('model-viewer')]
      const ready = [...expectedModelIds].every(id => {
        const matches = viewers.filter(viewer => viewer.dataset.layerId === id)
        return matches.length > 0 && matches.every(viewer => {
          const canvas = modelViewerCanvas(viewer)
          return viewer.loaded === true && Boolean(canvas && canvas.width > 8 && canvas.height > 8)
        })
      })
      if (ready) {
        // `loaded` fires when the GLB is available, but model-viewer's WebGL
        // renderer still needs a presentation cycle before its canvas can be
        // copied into the recorder's 2D canvas. Two RAFs prevent the capture
        // from starting with several seconds of transparent model frames.
        await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
        await new Promise(resolve => window.setTimeout(resolve, 250))
        return
      }
      await new Promise(resolve => window.setTimeout(resolve, 250))
    }
    throw new Error('The 3D models did not paint in time. Keep the 3D Video tab visible and try again.')
  }
  const applyRecipeScene = async (recipe: SceneRecipe, nextScene: Scene, status: (message: string) => void, prompt: string) => {
    recipeContextRef.current = { prompt, recipe }
    importScene(JSON.stringify(nextScene), `Recipe scene loaded: ${nextScene.name}`)
    await new Promise(resolve => window.setTimeout(resolve, 120))
    status('Waiting for 3D models to paint…')
    await waitForModelViewers()
    if (recipe.record !== true && recipe.save !== true) {
      status('3D models ready. Scene mounted; press Export MP4 when ready.')
    }
    if (recipe.record === true) {
      status('Recording scene…')
      const blob = await recordToBlob()
      status('Converting to MP4 and adding it to Videos…')
      const saved = await publishRecording(blob, nextScene)
      status(`MP4 ready in Videos: ${saved.name}`)
    }
    if (recipe.save === true) {
      status('Saving scene…')
      await persistScene()
    }
  }
  const persistScene = async () => {
    const current = sceneRef.current
    if (!current.layers.length) { setMessage('Add at least one layer before saving.'); return }
    setSaving(true); setMessage(null)
    try {
      const preview = document.createElement('canvas')
      const previewScale = Math.min(1, 1280 / Math.max(current.width, current.height))
      preview.width = Math.max(1, Math.round(current.width * previewScale)); preview.height = Math.max(1, Math.round(current.height * previewScale))
      paintScene(preview, progress)
      const layers = await Promise.all(current.layers.map(async layer => {
        if (layer.type === 'camera') return layer
        if (!layer.source.startsWith('blob:')) return layer
        const file = localFilesRef.current[layer.id]
        if (!file) return { ...layer, missingAsset: true }
        const uploaded = await uploadImage(file)
        return { ...layer, source: uploaded.url, missingAsset: false }
      }))
      const persisted = { ...current, layers }
      const saved = await saveSceneOutput(persisted, preview.toDataURL('image/png'))
      replaceScene(persisted); localFilesRef.current = {}; await loadOutputs()
      setMessage(`Scene saved to HocusPocus as ${saved.name}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Failed to save scene.')
    } finally {
      setSaving(false)
    }
  }
  const numberInput = (label: string, value: number, change: (value: number) => void, min = -100, max = 200, step = 1, disabled = false) => <label className="text-[10px] text-text-muted">{label}<input type="number" min={min} max={max} step={step} value={value} disabled={disabled} onChange={event => { const next = Number(event.target.value); if (Number.isFinite(next)) change(next) }} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs disabled:opacity-50" /></label>
  const mountNarrativeTemplate = () => {
    const asset = (name: string) => narrativeVisuals.find(item => item.name === name)
    const hero = asset(narrativeHero)
    const plate = asset(narrativePlate)
    const prop = asset(narrativeProp)
    const foreground = asset(narrativeForeground)
    const missing = narrativeTemplate.assetSlots.find(slot => slot.required && !({ hero, plate, prop, foreground }[slot.id]))
    if (missing) { setMessage(`Choose ${missing.label} before mounting this narrative scene.`); return }
    const asInput = (item: typeof hero) => item ? {
      source: item.url,
      type: item.type === 'model3d' ? 'model3d' as const : item.type === 'video' ? 'video' as const : 'image' as const,
      name: item.name,
    } : undefined
    const input: NarrativeTemplateInput = { hero: asInput(hero), plate: plate ? { ...asInput(plate)!, seamlessHorizontal: narrativePlateLoopReady } : undefined, prop: asInput(prop), foreground: asInput(foreground), width: scene.width, height: scene.height, fps, controls: { mood: narrativeMood, intensity: narrativeIntensity, direction: narrativeDirection, camera: narrativeCamera, palette: narrativePalette, voiceSpace: narrativeVoiceSpace } }
    const next = createNarrativeScene(narrativeTemplateId, input) as AnimatorScene
    updateScene(() => next)
    setSelectedId(next.layers.find(layer => layer.id === 'hero')?.id ?? next.layers.find(layer => layer.type !== 'camera')?.id ?? null)
    setSelectedKeyframeId(null); setSelectedEventId(null); setSelectedPresetId(''); setProgress(0)
    setMessage(`${narrativeTemplate.title} mounted as an editable ${next.duration}-second scene.`)
  }
  const sendImageToPanoramaLoop = () => {
    if (!selected || selected.type !== 'image' || !selected.source) return
    window.sessionStorage.setItem('hocuspocus:panorama-loop-source', JSON.stringify({ url: selected.source, name: selected.name }))
    setGenerationMode('image'); setSidebarMode('studio'); setSidebarOpen(true)
  }
  const attachSceneAudio = (filename: string, name = filename, kind: 'speech' | 'music' | 'sfx' | 'audio' = 'audio', prompt?: string, model?: string) => {
    if (!filename) return
    updateScene(current => {
      if ((current.audioTracks ?? []).some(track => track.filename === filename)) return current
      return { ...current, audioTracks: [...(current.audioTracks ?? []), { id: uid(), filename, name, kind, startTime: 0, volume: 1, prompt, model }] }
    })
  }
  const generateSceneSpeech = async () => {
    const prompt = sceneAudioPrompt.trim()
    if (!prompt) return
    setSceneAudioBusy(true); setSceneAudioError(null)
    try {
      const submitted = await submitGeneration({ model_type: selectedSpeechModel, generation_mode: 'audio', prompt, video_length: 0, image_mode: 0, multi_prompts_gen_type: 2, duration_seconds: sceneRef.current.duration, _audio_sub_mode: 'speech' })
      const deadline = Date.now() + 15 * 60_000
      let status = await fetchJobStatus(submitted.job_id)
      while (!['completed', 'failed', 'cancelled'].includes(status.status) && Date.now() < deadline) {
        await new Promise(resolve => window.setTimeout(resolve, 1000))
        status = await fetchJobStatus(submitted.job_id)
      }
      if (status.status !== 'completed') throw new Error(status.error || (Date.now() >= deadline ? 'Audio generation timed out.' : 'Audio generation did not complete.'))
      const filename = status.output_files.find(file => /\.(wav|mp3|m4a|aac|flac|ogg)$/i.test(file)) ?? status.output_files[0]
      if (!filename) throw new Error('The audio model completed without an output file.')
      attachSceneAudio(filename, filename.replace(/\.[^.]+$/, ''), 'speech', prompt, selectedSpeechModel)
      setSceneAudioPrompt(''); await loadOutputs(); setMessage('Generated speech attached to this scene.')
    } catch (error) {
      setSceneAudioError(error instanceof Error ? error.message : 'Could not generate scene speech.')
    } finally {
      setSceneAudioBusy(false)
    }
  }
  const proposeCopilotEdit = async () => {
    if (!selected || !copilotIntent.trim()) return
    if (selected.locked) { setCopilotError('Unlock this layer before asking the copilot to change it.'); return }
    setCopilotBusy(true); setCopilotError(null); setCopilotProposal(null)
    try {
      const text = await generateLlmText({
        prompt: `USER INTENT:\n${copilotIntent.trim()}`,
        system_prompt: buildSceneCopilotSystemPrompt(sceneRef.current, selected, clipsByLayer[selected.id] ?? []),
        max_new_tokens: 1200,
        temperature: .1,
        top_p: .8,
        json_schema: SCENE_COPILOT_JSON_SCHEMA,
      })
      setCopilotProposal(parseSceneCopilotProposal(text, sceneRef.current, selected.id, 'layer', clipsByLayer[selected.id] ?? [])); setCopilotProposalRevision(historyRevisionRef.current)
    } catch (error) {
      setCopilotError(error instanceof Error ? error.message : 'The copilot could not prepare this edit.')
    } finally {
      setCopilotBusy(false)
    }
  }
  const applyCopilotEdit = () => {
    if (!copilotProposal) return
    if (copilotProposalRevision !== historyRevisionRef.current) { setCopilotProposal(null); setCopilotProposalRevision(null); setCopilotError('The scene changed while this proposal was being reviewed. Ask the copilot again.'); return }
    const proposal = copilotProposal
    const selectedLayerId = selected?.id
    updateScene(current => ({
      ...(applySceneCopilotProposal(current, proposal) as AnimatorScene),
      copilotAudit: [...(current.copilotAudit ?? []), {
        id: uid(),
        createdAt: new Date().toISOString(),
        scope: 'layer' as const,
        selectedLayerId,
        intent: copilotIntent.trim(),
        summary: proposal.summary,
        operations: proposal.operations.map(operation => ({ ...operation })),
        validation: 'applied' as const,
        model: 'configured-llm',
      }].slice(-100),
    }))
    setMessage(`Copilot applied: ${copilotProposal.summary}`)
    setCopilotProposal(null); setCopilotProposalRevision(null)
  }
  const proposeSceneCopilotEdit = async () => {
    if (!sceneCopilotIntent.trim()) return
    setSceneCopilotBusy(true); setSceneCopilotError(null); setSceneCopilotProposal(null)
    try {
      const text = await generateLlmText({
        prompt: `USER INTENT:\n${sceneCopilotIntent.trim()}`,
        system_prompt: buildSceneScopeCopilotSystemPrompt(sceneRef.current),
        max_new_tokens: 900,
        temperature: .1,
        top_p: .8,
        json_schema: SCENE_COPILOT_JSON_SCHEMA,
      })
      setSceneCopilotProposal(parseSceneCopilotProposal(text, sceneRef.current, undefined, 'scene')); setSceneCopilotProposalRevision(historyRevisionRef.current)
    } catch (error) {
      setSceneCopilotError(error instanceof Error ? error.message : 'The copilot could not prepare this scene edit.')
    } finally {
      setSceneCopilotBusy(false)
    }
  }
  const applySceneCopilotEdit = () => {
    if (!sceneCopilotProposal) return
    if (sceneCopilotProposalRevision !== historyRevisionRef.current) { setSceneCopilotProposal(null); setSceneCopilotProposalRevision(null); setSceneCopilotError('The scene changed while this proposal was being reviewed. Ask the copilot again.'); return }
    const proposal = sceneCopilotProposal
    updateScene(current => ({
      ...(applySceneCopilotProposal(current, proposal) as AnimatorScene),
      copilotAudit: [...(current.copilotAudit ?? []), {
        id: uid(), createdAt: new Date().toISOString(), scope: 'scene' as const,
        intent: sceneCopilotIntent.trim(), summary: proposal.summary,
        operations: proposal.operations.map(operation => ({ ...operation })), validation: 'applied' as const, model: 'configured-llm',
      }].slice(-100),
    }))
    setMessage(`Scene copilot applied: ${proposal.summary}`)
    setSceneCopilotProposal(null); setSceneCopilotProposalRevision(null)
  }
  const dictateCopilotIntent = () => {
    const root = window as unknown as { SpeechRecognition?: SpeechRecognizerConstructor; webkitSpeechRecognition?: SpeechRecognizerConstructor }
    const Recognition = root.SpeechRecognition ?? root.webkitSpeechRecognition
    if (!Recognition) { setCopilotError('Voice input is not available in this browser. Type the instruction instead.'); return }
    const recognition = new Recognition()
    recognition.lang = navigator.language || 'en-US'; recognition.continuous = false; recognition.interimResults = false
    recognition.onresult = event => {
      const transcript = Array.from(event.results).flatMap(result => Array.from(result)).map(result => result.transcript).join(' ').trim()
      if (transcript) setCopilotIntent(current => current ? `${current} ${transcript}` : transcript)
    }
    recognition.onerror = () => setCopilotError('Voice input was unavailable. You can still type the instruction.')
    recognition.onend = () => setCopilotListening(false)
    setCopilotError(null); setCopilotListening(true); recognition.start()
  }
  const orbitPivot = (() => {
    if (!selected || !isVisualLayer(selected)) return null
    const orbit = selected?.animation.orbit
    const target = orbit && scene.layers.find(layer => layer.id === orbit.targetLayerId)
    if (!orbit || !target || !isVisualLayer(target)) return null
    const targetState = layerState(target, progress)
    return applyCameraTransform({ ...targetState, x: targetState.x + (orbit.centerOffsetX ?? 0), y: targetState.y + (orbit.centerOffsetY ?? 0) }, selected, progress)
  })()
  const renderLayer = (layer: AnimatorLayer) => {
    if (layer.type === 'camera') return null
    const effects = normalizedEffects(layer.effects)
    const states = renderedLayerStates(layer)
    const selection = selectedId === layer.id
    const effectStyle: CSSProperties = { filter: effectFilter(effects, previewShortSide / 100) }
    const previewHeight = previewWidth * scene.height / Math.max(1, scene.width)
    if (!layer.visible) return null
    const edgeMove = (event: ReactPointerEvent<HTMLElement>) => { if (layer.type !== 'model3d') return startGesture(event, layer, 'move'); const box = event.currentTarget.getBoundingClientRect(); const edge = (event.clientX - box.left) / box.width < .18 || (event.clientX - box.left) / box.width > .82 || (event.clientY - box.top) / box.height < .18 || (event.clientY - box.top) / box.height > .82; startGesture(event, layer, edge ? 'move' : 'orbit') }
    return states.map((state, index) => {
      const common: CSSProperties = { left: `${state.x}%`, top: `${state.y}%`, width: `${(layer.type === 'model3d' ? 52 : 100) * state.scale}%`, height: `${(layer.type === 'model3d' ? 75 : 100) * state.scale}%`, opacity: state.opacity, zIndex: state.z, transform: `translate(-50%, -50%) rotate(${state.rotation}deg)`, mixBlendMode: effects.blendMode }
      const layerShortSide = Math.min(previewWidth * (layer.type === 'model3d' ? .52 : 1) * state.scale, previewHeight * (layer.type === 'model3d' ? .75 : 1) * state.scale)
      const maskStyle: CSSProperties = { overflow: 'hidden', borderRadius: effects.mask === 'ellipse' ? '50%' : effects.mask === 'rounded' ? `${layerShortSide * effects.maskRadius / 100}px` : undefined }
      const isPrimary = index === 0
      if (layer.missingAsset) return isPrimary ? <button key={`${layer.id}-missing`} onClick={() => setSelectedId(layer.id)} className={`absolute flex items-center justify-center border border-dashed border-red-400/70 bg-red-500/10 text-[10px] text-red-300 ${selection ? 'ring-2 ring-accent-blue ring-inset' : ''}`} style={common}>Missing asset</button> : null
      const atmosphere = layer.type === 'effect' ? normalizedAtmosphere(layer.atmosphere) : null
      const media = atmosphere
        ? <AtmospherePreview atmosphere={atmosphere} seconds={progress * scene.duration} width={previewWidth} height={previewHeight} layerId={layer.id} />
        : layer.type === 'model3d'
        ? <model-viewer data-layer-id={layer.id} src={layer.source} orientation={`0deg ${state.modelYaw ?? 0}deg 0deg`} camera-orbit={`${layer.transform.rotationY ?? 0}deg ${layer.transform.rotationX ?? 75}deg auto`} interaction-prompt="none" animation-name={layer.animation.clip || undefined} animation-crossfade-duration="0" onLoad={() => syncSceneMedia(progressRef.current * sceneRef.current.duration)} shadow-intensity="1" exposure="1" loading="eager" className="scene-animator-model pointer-events-none h-full w-full" />
        : layer.type === 'video'
          ? <video data-layer-id={layer.id} ref={isPrimary ? element => { videoRefs.current[layer.id] = element } : undefined} src={layer.source} muted playsInline preload="auto" onLoadedMetadata={() => syncSceneMedia(progressRef.current * sceneRef.current.duration)} className={`h-full w-full ${layer.fill ? 'object-cover' : 'object-contain'}`} />
          : <img data-layer-id={layer.id} src={layer.source} alt={layer.name} draggable={false} className={`h-full w-full select-none ${layer.fill ? 'object-cover' : 'object-contain'}`} />
      return <div key={`${layer.id}-${index}`} style={common} onPointerDown={layer.type === 'effect' ? undefined : edgeMove} onPointerMove={layer.type === 'effect' ? undefined : moveGesture} onPointerUp={layer.type === 'effect' ? undefined : endGesture} onPointerCancel={layer.type === 'effect' ? undefined : endGesture} className={`absolute touch-none ${layer.type === 'effect' ? 'pointer-events-none' : 'cursor-grab active:cursor-grabbing'} ${selection && isPrimary ? 'ring-2 ring-accent-blue ring-inset' : ''}`}><div className="h-full w-full" style={maskStyle}><div className="h-full w-full" style={effectStyle}>{media}</div></div>{selection && isPrimary && layer.type !== 'effect' && <button aria-label="Resize layer" onPointerDown={event => startGesture(event, layer, 'resize')} onPointerMove={moveGesture} onPointerUp={endGesture} className="absolute -bottom-1.5 -right-1.5 h-3.5 w-3.5 cursor-nwse-resize rounded-sm border border-white bg-accent-blue shadow" />}</div>
    }).concat(seamCoverStates(layer).map((state, index) => {
      const kind = normalizedStrip(layer.strip).seamOccluder.kind
      const coverScale = normalizedStrip(layer.strip).seamOccluder.scale
      const cover: CSSProperties = { left: `${state.x}%`, top: `${state.y}%`, width: `${8 * coverScale}%`, height: `${92 * coverScale}%`, opacity: state.opacity, zIndex: 18, transform: `translate(-50%, -50%) rotate(${state.rotation}deg)`, pointerEvents: 'none' }
      return <div key={`${layer.id}-seam-${index}`} className="absolute" style={cover}><img src={seamOccluderDataUri(kind)} alt="" draggable={false} className="h-full w-full object-contain object-bottom select-none" /></div>
    }))
  }
  const activeCamera = activeCameraLayer()
  const selectedEffects = selected && isVisualLayer(selected) ? normalizedEffects(selected.effects) : null
  const selectedStrip = selected && isVisualLayer(selected) ? normalizedStrip(selected.strip) : null
  const selectedAtmosphere = selected?.type === 'effect' ? normalizedAtmosphere(selected.atmosphere) : null
  const selectedClipDuration = selected ? clipDurationsByLayer[selected.id] ?? 0 : 0
  const relationshipTargets = selected ? scene.layers.filter(layer => layer.id !== selected.id && isVisualLayer(layer) && !dependencyWouldCycle(selected.id, layer.id)) : []
  const canUndo = historyRevision >= 0 && pastScenesRef.current.length > 0
  const canRedo = historyRevision >= 0 && futureScenesRef.current.length > 0
  const verticalSafeWidth = Math.min(100, (9 / 16) / (scene.width / Math.max(1, scene.height)) * 100)

  return <div className="flex min-h-[620px] flex-col overflow-hidden rounded-xl border border-border bg-bg-tertiary xl:flex-row">
    <section className="flex min-w-0 flex-1 flex-col p-3 md:p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-1.5 text-xs font-medium"><Film size={15} className="text-accent-blue" /><input value={scene.name} onChange={event => updateScene(current => ({ ...current, name: event.target.value }))} aria-label="Scene name" className="w-44 rounded border border-transparent bg-transparent px-1 py-0.5 text-xs font-medium hover:border-border focus:border-accent-blue focus:outline-none" /><span className="text-[10px] font-normal text-text-muted">{scene.width}×{scene.height}</span></div><div className="flex flex-wrap gap-2"><button type="button" onClick={() => setLibraryOpen(true)} disabled={playing || recording || publishing} className="rounded border border-border bg-bg-primary px-2.5 py-1.5 text-[10px] flex items-center gap-1 disabled:opacity-50"><FolderOpen size={12} /> Open scene</button><button type="button" onClick={() => void persistScene()} disabled={saving || !scene.layers.length || playing || recording || publishing} className="rounded border border-accent-blue/40 bg-accent-blue/10 px-2.5 py-1.5 text-[10px] text-accent-blue flex items-center gap-1 disabled:opacity-50">{saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}{saving ? 'Saving…' : 'Save scene'}</button><button onClick={play} disabled={!scene.layers.length || playing || recording || publishing} className="rounded border border-border bg-bg-primary px-2.5 py-1.5 text-[10px] flex items-center gap-1 disabled:opacity-50"><Play size={12} /> Preview</button><button onClick={record} disabled={recording || playing || publishing} className="rounded bg-cta px-2.5 py-1.5 text-[10px] text-white flex items-center gap-1 disabled:opacity-50">{recording || publishing ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}{recording ? 'Recording…' : publishing ? 'Saving MP4…' : 'Export MP4'}</button></div></div>
      <div className="mb-2 flex items-center justify-end gap-1.5"><button type="button" onClick={undoScene} disabled={!canUndo} title="Undo (Ctrl/Cmd+Z)" className="rounded border border-border bg-bg-primary p-1.5 disabled:opacity-30"><Undo2 size={12} /></button><button type="button" onClick={redoScene} disabled={!canRedo} title="Redo (Ctrl/Cmd+Shift+Z)" className="rounded border border-border bg-bg-primary p-1.5 disabled:opacity-30"><Redo2 size={12} /></button><span className="ml-1 text-[8px] text-text-muted">{lastAutosaveAt ? `Autosaved ${new Date(lastAutosaveAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Autosave waiting…'}</span></div>
      <div className="mb-3 flex flex-wrap items-center gap-1">{RESOLUTIONS.map(([label, width, height]) => <button key={label} disabled={playing || recording} onClick={() => updateScene(current => ({ ...current, width, height }))} className={`rounded border px-1.5 py-1 text-[9px] disabled:opacity-40 ${scene.width === width && scene.height === height ? 'border-accent-blue bg-accent-blue/15 text-accent-blue' : 'border-border bg-bg-primary text-text-muted'}`}>{label}</button>)}<span className="ml-auto flex items-center gap-1 pl-2 text-[8px] text-text-muted">Frame rate{([30, 60] as SceneFrameRate[]).map(rate => <button key={rate} type="button" disabled={playing || recording} onClick={() => updateScene(current => ({ ...current, fps: rate }))} className={`rounded border px-1.5 py-1 text-[9px] disabled:opacity-40 ${fps === rate ? 'border-purple-300 bg-purple-400/10 text-purple-200' : 'border-border bg-bg-primary text-text-muted'}`}>{rate} FPS</button>)}</span></div>
      <div className="mb-3 flex flex-wrap items-center gap-1.5 rounded border border-border bg-bg-secondary p-1.5">
        <button type="button" onClick={() => updateScene(current => ({ ...current, composition: { ...composition, showGrid: !composition.showGrid } }))} className={`flex items-center gap-1 rounded border px-1.5 py-1 text-[9px] ${composition.showGrid ? 'border-accent-blue bg-accent-blue/10 text-accent-blue' : 'border-border text-text-muted'}`}><Grid3X3 size={10} /> Grid</button>
        <button type="button" onClick={() => updateScene(current => ({ ...current, composition: { ...composition, snap: !composition.snap } }))} className={`flex items-center gap-1 rounded border px-1.5 py-1 text-[9px] ${composition.snap ? 'border-purple-300 bg-purple-400/10 text-purple-200' : 'border-border text-text-muted'}`}><Magnet size={10} /> Snap</button>
        <label className="flex items-center gap-1 text-[8px] text-text-muted">Grid %<input type="number" min={1} max={50} step={1} value={composition.gridSize} onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value)) updateScene(current => ({ ...current, composition: { ...composition, gridSize: Math.max(1, Math.min(50, value)) } })) }} className="w-12 rounded border border-border bg-bg-primary px-1 py-1 text-[9px]" /></label>
        <label className="ml-auto flex items-center gap-1 text-[8px] text-text-muted">Safe area<select value={composition.safeArea} onChange={event => updateScene(current => ({ ...current, composition: { ...composition, safeArea: event.target.value as NonNullable<Scene['composition']>['safeArea'] } }))} className="rounded border border-border bg-bg-primary px-1 py-1 text-[9px]"><option value="none">Off</option><option value="action">Action 90%</option><option value="title">Title 80%</option><option value="vertical">9:16 social</option><option value="all">All guides</option></select></label>
        {selected && isVisualLayer(selected) && <><button type="button" disabled={selected.locked} onClick={() => translateLayer(selected.id, 50, selected.transform.y, false)} title="Center horizontally" className="rounded border border-border p-1 text-text-muted disabled:opacity-30"><AlignHorizontalJustifyCenter size={11} /></button><button type="button" disabled={selected.locked} onClick={() => translateLayer(selected.id, selected.transform.x, 50, false)} title="Center vertically" className="rounded border border-border p-1 text-text-muted disabled:opacity-30"><AlignVerticalJustifyCenter size={11} /></button></>}
      </div>
      {selected && isVisualLayer(selected) && selected.type !== 'model3d' && selected.type !== 'effect' && <button onClick={() => updateLayer(selected.id, layer => ({ ...layer, fill: !layer.fill, transform: { ...layer.transform, x: 50, y: 50, scale: 1 }, animation: mapSceneAnimationPoints(layer, point => ({ ...point, x: 50, y: 50, scale: 1 })) }))} className={`mb-3 rounded border px-2 py-1 text-[10px] ${selected.fill ? 'border-accent-blue bg-accent-blue/15 text-accent-blue' : 'border-border bg-bg-primary text-text-secondary'}`}>{selected.fill ? 'Fill screen enabled' : 'Fill screen'}</button>}
      {selected && isVisualLayer(selected) && selected.type !== 'model3d' && selected.type !== 'effect' && <button onClick={() => { sendToBack(selected.id); applyParallaxPreset(selected.id, 'background') }} className="mb-3 ml-1 rounded border border-border bg-bg-primary px-2 py-1 text-[10px] text-text-secondary">Use as background</button>}
      <div className="flex w-full justify-center">
      <div ref={canvasRef} className="relative isolate w-full overflow-hidden rounded-lg border border-border bg-[#0b1020]" style={{ aspectRatio: `${scene.width} / ${scene.height}`, maxWidth: `${68 * scene.width / scene.height}vh` }}>
        {[...scene.layers].sort((a, b) => a.z - b.z).map(renderLayer)}
        {composition.showGrid && <div className="pointer-events-none absolute inset-0 z-[990] opacity-35" style={{ backgroundImage: 'linear-gradient(to right, rgba(125,211,252,.55) 1px, transparent 1px), linear-gradient(to bottom, rgba(125,211,252,.55) 1px, transparent 1px)', backgroundSize: `${composition.gridSize}% ${composition.gridSize}%` }} />}
        {(composition.safeArea === 'action' || composition.safeArea === 'all') && <div className="pointer-events-none absolute inset-[5%] z-[991] border border-dashed border-emerald-300/80"><span className="absolute left-1 top-1 rounded bg-black/55 px-1 text-[7px] text-emerald-200">Action safe 90%</span></div>}
        {(composition.safeArea === 'title' || composition.safeArea === 'all') && <div className="pointer-events-none absolute inset-[10%] z-[992] border border-dashed border-amber-300/80"><span className="absolute right-1 top-1 rounded bg-black/55 px-1 text-[7px] text-amber-200">Title safe 80%</span></div>}
        {(composition.safeArea === 'vertical' || composition.safeArea === 'all') && <div className="pointer-events-none absolute inset-y-0 left-1/2 z-[993] -translate-x-1/2 border-x border-dashed border-fuchsia-300/90 bg-fuchsia-400/[.03]" style={{ width: `${verticalSafeWidth}%` }}><span className="absolute left-1 top-1 rounded bg-black/55 px-1 text-[7px] text-fuchsia-200">9:16 social</span></div>}
        {activeCamera && <div className="pointer-events-none absolute left-2 top-2 z-[997] flex items-center gap-1 rounded bg-black/55 px-1.5 py-1 text-[8px] text-cyan-200"><Camera size={10} /> {activeCamera.name}</div>}
        {orbitPivot && <div className="pointer-events-none absolute z-[998] h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-cyan-300 bg-cyan-400/20 shadow-[0_0_8px_rgba(103,232,249,.9)]" style={{ left: `${orbitPivot.x}%`, top: `${orbitPivot.y}%` }}><span className="absolute left-1/2 top-[-5px] h-6 w-px -translate-x-1/2 bg-cyan-300/80" /><span className="absolute left-[-5px] top-1/2 h-px w-6 -translate-y-1/2 bg-cyan-300/80" /></div>}
        {flash && <div className="pointer-events-none absolute z-[999]" style={{ left: `${flash.x}%`, top: `${flash.y}%` }}><span className="absolute -left-6 -top-6 h-12 w-12 rounded-full border-2 border-white/90 animate-ping" /><span className="absolute -left-1.5 -top-1.5 h-3 w-3 rounded-full bg-white shadow-[0_0_20px_8px_rgba(96,165,250,.9)]" /></div>}
        <div className="absolute inset-x-0 bottom-0 z-[1000] h-1 bg-black/40"><div className="h-full bg-accent-blue" style={{ width: `${progress * 100}%` }} /></div>
      </div>
      </div>
      <p className="mt-2 text-[9px] text-text-muted">Center-drag a 3D layer to orbit it 360°; drag its outer edge to move it. Camera layers animate pan, zoom and rotation without rendering an asset. Parallax controls how strongly each visual layer follows camera pan. WebM uses the same camera transform and Z order as this preview.</p>
      <SceneTimeline
        layers={scene.layers}
        duration={scene.duration}
        fps={fps}
        currentTime={progress * scene.duration}
        selectedLayerId={selectedId}
        selectedKeyframeId={selectedKeyframeId}
        selectedEventId={selectedEventId}
        onScrub={time => { if (recording) return; if (animationRef.current) cancelAnimationFrame(animationRef.current); setPlaying(false); syncSceneMedia(time); setProgress(Math.max(0, Math.min(1, time / Math.max(.1, scene.duration)))) }}
        onSelectLayer={id => { setSelectedId(id); setSelectedKeyframeId(null); setSelectedEventId(null) }}
        onSelectKeyframe={(layerId, keyframeId, time) => { if (recording) return; setSelectedId(layerId); setSelectedKeyframeId(keyframeId); setSelectedEventId(null); syncSceneMedia(time); setProgress(Math.max(0, Math.min(1, time / Math.max(.1, scene.duration)))) }}
        onSelectEvent={(layerId, eventId, time) => { if (recording) return; setSelectedId(layerId); setSelectedKeyframeId(null); setSelectedEventId(eventId); syncSceneMedia(time); setProgress(Math.max(0, Math.min(1, time / Math.max(.1, scene.duration)))) }}
        onAddKeyframe={addKeyframeAtPlayhead}
        onAddEvent={addEventAtPlayhead}
        onDeleteKeyframe={deleteTimelineKeyframe}
        onDeleteEvent={deleteTimelineEvent}
        onCopyKeyframes={copyTimelineKeyframes}
        onPasteKeyframes={() => void pasteTimelineKeyframes()}
        onUpdateKeyframe={updateTimelineKeyframe}
        onUpdateEvent={updateTimelineEvent}
        onUpdateTiming={patch => selected && updateLayerTiming(selected.id, patch)}
      />
    </section>
    <aside className="w-full shrink-0 border-t border-border bg-bg-secondary p-3 overflow-y-auto space-y-3 xl:w-[300px] xl:border-l xl:border-t-0">
      <div className="space-y-2 rounded border border-fuchsia-400/30 bg-fuchsia-400/[.045] p-2">
        <div className="flex items-center justify-between gap-2"><span className="text-[10px] font-medium uppercase tracking-wider text-fuchsia-100">Narrative scenes</span><span className="text-[8px] text-fuchsia-200/70">10–12s editable shots</span></div>
        <select value={narrativeTemplateId} disabled={playing || recording || publishing} onChange={event => setNarrativeTemplateId(event.target.value as NarrativeSceneId)} className="w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]">
          {NARRATIVE_SCENE_TEMPLATES.map(template => <option key={template.id} value={template.id}>{template.experimental ? 'Experimental · ' : ''}{template.title}</option>)}
        </select>
        <div className="grid grid-cols-2 gap-1">{NARRATIVE_SCENE_TEMPLATES.map(template => <button key={template.id} type="button" disabled={playing || recording || publishing} onClick={() => setNarrativeTemplateId(template.id)} title={template.description} className={`rounded border p-1 text-left disabled:opacity-40 ${narrativeTemplateId === template.id ? 'border-fuchsia-300/70 bg-fuchsia-400/15 text-fuchsia-100' : 'border-border bg-bg-primary text-text-secondary hover:border-fuchsia-300/40'}`}><span className="block truncate text-[8px] font-medium">{template.experimental ? 'Experimental · ' : ''}{template.title}</span><span className="block text-[7px] text-text-muted">{template.defaultDuration}s · {template.assetSlots.filter(slot => slot.required).length} assets</span></button>)}</div>
        <p className="text-[8px] leading-relaxed text-text-muted">{narrativeTemplate.description}</p>
        <label className="block text-[9px] text-text-muted">Character / subject<select value={narrativeHero} onChange={event => setNarrativeHero(event.target.value)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]"><option value="">Choose asset…</option>{narrativeVisuals.map(asset => <option key={asset.name} value={asset.name}>{asset.type === 'model3d' ? '3D · ' : asset.type === 'video' ? 'Video · ' : 'Image · '}{asset.name}</option>)}</select></label>
        {narrativeHero && <p className={`rounded border px-1.5 py-1 text-[8px] leading-relaxed ${narrativeSuitability('hero', narrativeHero).level === 'warning' ? 'border-amber-300/25 bg-amber-400/[.06] text-amber-100' : 'border-emerald-300/20 bg-emerald-400/[.04] text-emerald-100'}`}>{narrativeSuitability('hero', narrativeHero).message}</p>}
        <label className="block text-[9px] text-text-muted">Background<select value={narrativePlate} onChange={event => { setNarrativePlate(event.target.value); setNarrativePlateLoopReady(false) }} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]"><option value="">Choose asset…</option>{generatedMedia.map(asset => <option key={asset.name} value={asset.name}>{asset.type === 'video' ? 'Video · ' : 'Image · '}{asset.name}</option>)}</select></label>
        {narrativePlate && narrativeSuitability('plate', narrativePlate).level !== 'ok' && <p className="rounded border border-cyan-300/20 bg-cyan-400/[.04] px-1.5 py-1 text-[8px] leading-relaxed text-cyan-100">{narrativeSuitability('plate', narrativePlate).message}</p>}
        {narrativePlate && <label className="flex items-start gap-1.5 rounded border border-amber-300/20 bg-amber-400/[.035] p-1.5 text-[8px] leading-relaxed text-amber-100"><input type="checkbox" checked={narrativePlateLoopReady} onChange={event => setNarrativePlateLoopReady(event.target.checked)} className="mt-0.5" /> <span><strong>Loop-ready horizontally</strong><br />I reviewed this plate in Fondo infinito (or it is a verified panorama). This enables the cylinder A/B preview; it does not claim the model repaired the seam mathematically.</span></label>}
        {narrativeTemplate.assetSlots.some(slot => slot.id === 'prop') && <label className="block text-[9px] text-text-muted">Object / portal{narrativeTemplate.assetSlots.find(slot => slot.id === 'prop')?.required ? '' : ' (optional)'}<select value={narrativeProp} onChange={event => setNarrativeProp(event.target.value)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]"><option value="">None</option>{narrativeVisuals.map(asset => <option key={asset.name} value={asset.name}>{asset.name}</option>)}</select></label>}
        {narrativeTemplate.assetSlots.some(slot => slot.id === 'foreground') && <label className="block text-[9px] text-text-muted">Foreground (optional)<select value={narrativeForeground} onChange={event => setNarrativeForeground(event.target.value)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]"><option value="">None</option>{generatedMedia.map(asset => <option key={asset.name} value={asset.name}>{asset.name}</option>)}</select></label>}
        <div className="grid grid-cols-2 gap-1 text-[9px] text-text-muted">
          {narrativeTemplate.controls.includes('mood') && <label>Mood<select value={narrativeMood} onChange={event => setNarrativeMood(event.target.value as typeof narrativeMood)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[9px]"><option value="calm">Calm</option><option value="tense">Tense</option><option value="dreamy">Dreamy</option><option value="heroic">Heroic</option></select></label>}
          {narrativeTemplate.controls.includes('intensity') && <label>Intensity<select value={narrativeIntensity} onChange={event => setNarrativeIntensity(Number(event.target.value) as 1 | 2 | 3)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[9px]"><option value={1}>Low</option><option value={2}>Medium</option><option value={3}>High</option></select></label>}
          {narrativeTemplate.controls.includes('direction') && <label>Direction<select value={narrativeDirection} onChange={event => setNarrativeDirection(event.target.value as typeof narrativeDirection)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[9px]"><option value="right">Right</option><option value="left">Left</option></select></label>}
          {narrativeTemplate.controls.includes('camera') && <label>Camera<select value={narrativeCamera} onChange={event => setNarrativeCamera(event.target.value as typeof narrativeCamera)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[9px]"><option value="restrained">Restrained</option><option value="push">Push</option><option value="drift">Drift</option></select></label>}
          {narrativeTemplate.controls.includes('palette') && <label>Palette<select value={narrativePalette} onChange={event => setNarrativePalette(event.target.value as typeof narrativePalette)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[9px]"><option value="natural">Natural</option><option value="cool">Cool</option><option value="warm">Warm</option><option value="neon">Neon</option></select></label>}
          {narrativeTemplate.controls.includes('voiceSpace') && <label>Voice space<select value={narrativeVoiceSpace} onChange={event => setNarrativeVoiceSpace(event.target.value as typeof narrativeVoiceSpace)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[9px]"><option value="center">Center</option><option value="left">Left</option><option value="right">Right</option></select></label>}
        </div>
        <button type="button" disabled={playing || recording || publishing} onClick={mountNarrativeTemplate} className="w-full rounded border border-fuchsia-300/50 bg-fuchsia-400/10 px-2 py-1.5 text-[10px] text-fuchsia-100 hover:bg-fuchsia-400/20 disabled:opacity-40">Mount editable scene</button>
      </div>
      <div className="space-y-1.5 rounded border border-cyan-400/30 bg-cyan-400/[.04] p-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-cyan-100">Instruct scene</span><span className="text-[8px] text-cyan-200/80">Camera + grade + links</span></div>
        <p className="text-[8px] leading-relaxed text-text-muted">Ask for a restrained global camera move, visual mood, or an explicit link between existing layers. Links always require confirmation; it cannot add, remove, move, or replace assets.</p>
        <textarea value={sceneCopilotIntent} disabled={sceneCopilotBusy} onChange={event => setSceneCopilotIntent(event.target.value)} placeholder="Make the camera drift slowly and give the whole scene a cool, dreamy tone…" rows={2} className="w-full resize-y rounded border border-border bg-bg-primary px-2 py-1 text-[10px] disabled:opacity-50" />
        <button type="button" disabled={!sceneCopilotIntent.trim() || sceneCopilotBusy} onClick={() => void proposeSceneCopilotEdit()} className="w-full rounded border border-cyan-300/50 bg-cyan-400/10 px-2 py-1 text-[10px] text-cyan-100 disabled:opacity-40">{sceneCopilotBusy ? 'Planning scene edit…' : 'Propose scene changes'}</button>
        {sceneCopilotError && <p className="text-[8px] text-red-300">{sceneCopilotError}</p>}
        {sceneCopilotProposal && <div className="space-y-1 rounded border border-cyan-300/25 bg-black/15 p-1.5"><p className="text-[9px] text-cyan-100">{sceneCopilotProposal.summary}</p><ul className="space-y-0.5 text-[8px] text-text-secondary">{describeSceneCopilotProposal(scene, sceneCopilotProposal).map(line => <li key={line}>• {line}</li>)}</ul><div className="flex gap-1"><button type="button" onClick={applySceneCopilotEdit} className="flex-1 rounded bg-cyan-400/20 px-1.5 py-1 text-[9px] text-cyan-100">Apply</button><button type="button" onClick={() => setSceneCopilotProposal(null)} className="rounded border border-border px-1.5 py-1 text-[9px] text-text-muted">Discard</button></div></div>}
      </div>
      <div className="space-y-1.5 rounded border border-amber-400/30 bg-amber-400/[.04] p-2">
        <div className="flex items-center justify-between gap-2"><span className="text-[10px] font-medium text-amber-100">Scene audio</span><span className="text-[8px] text-amber-200/75">Rendered into MP4</span></div>
        <p className="text-[8px] leading-relaxed text-text-muted">Generate narration with the installed audio model, or attach an existing audio output. Prompt, model, start time and volume stay with the scene and its exported metadata.</p>
        <textarea value={sceneAudioPrompt} disabled={sceneAudioBusy || playing || recording || publishing} onChange={event => setSceneAudioPrompt(event.target.value)} placeholder="A calm inner voice: ‘I know this place…’" rows={2} className="w-full resize-y rounded border border-border bg-bg-primary px-2 py-1 text-[10px] disabled:opacity-50" />
        <button type="button" disabled={!sceneAudioPrompt.trim() || sceneAudioBusy || playing || recording || publishing} onClick={() => void generateSceneSpeech()} className="w-full rounded border border-amber-300/50 bg-amber-400/10 px-2 py-1 text-[10px] text-amber-100 disabled:opacity-40">{sceneAudioBusy ? 'Generating narration…' : `Generate speech · ${selectedSpeechModel}`}</button>
        {generatedAudio.length > 0 && <label className="block text-[9px] text-text-muted">Attach existing output<select defaultValue="" onChange={event => { const output = generatedAudio.find(item => item.name === event.target.value); if (output) attachSceneAudio(output.name, output.name.replace(/\.[^.]+$/, ''), 'audio'); event.currentTarget.value = '' }} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]"><option value="">Choose audio…</option>{generatedAudio.map(output => <option key={output.name} value={output.name}>{output.name}</option>)}</select></label>}
        {(scene.audioTracks ?? []).length > 0 && <div className="space-y-1 rounded border border-amber-300/15 bg-black/15 p-1.5">{scene.audioTracks!.map(track => <div key={track.id} className="grid grid-cols-[1fr_44px_44px_18px] items-center gap-1 text-[8px]"><span title={track.prompt ?? track.name} className="truncate text-amber-100">{track.kind} · {track.name}</span><label className="text-text-muted">at<input aria-label={`Start ${track.name}`} type="number" min="0" max={scene.duration} step="0.1" value={track.startTime} onChange={event => { const startTime = Number(event.target.value); if (Number.isFinite(startTime)) updateScene(current => ({ ...current, audioTracks: (current.audioTracks ?? []).map(item => item.id === track.id ? { ...item, startTime: Math.max(0, Math.min(current.duration, startTime)) } : item) })) }} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-0.5 text-[8px]" /></label><label className="text-text-muted">vol<input aria-label={`Volume ${track.name}`} type="number" min="0" max="2" step="0.1" value={track.volume} onChange={event => { const volume = Number(event.target.value); if (Number.isFinite(volume)) updateScene(current => ({ ...current, audioTracks: (current.audioTracks ?? []).map(item => item.id === track.id ? { ...item, volume: Math.max(0, Math.min(2, volume)) } : item) })) }} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-0.5 text-[8px]" /></label><button type="button" title={`Remove ${track.name}`} onClick={() => updateScene(current => ({ ...current, audioTracks: (current.audioTracks ?? []).filter(item => item.id !== track.id) }))} className="mt-3 text-red-300"><Trash2 size={12} /></button></div>)}</div>}
        {sceneAudioError && <p className="text-[8px] text-red-300">{sceneAudioError}</p>}
      </div>
      {selected && <div className="space-y-1 rounded border border-fuchsia-400/20 bg-fuchsia-400/[.025] p-2"><div className="text-[9px] text-fuchsia-100">Suggestions for {selected.name}</div><div className="flex flex-wrap gap-1">{copilotSuggestions.map(suggestion => <button key={suggestion} type="button" disabled={copilotBusy || selected.locked} onClick={() => { setCopilotIntent(suggestion); setCopilotError(null) }} className="rounded border border-fuchsia-300/25 px-1.5 py-0.5 text-left text-[8px] text-fuchsia-100 hover:bg-fuchsia-400/10 disabled:opacity-40">{suggestion}</button>)}</div></div>}
      <SceneRecipePanel disabled={playing || recording || publishing || saving} outputs={outputs} onApply={applyRecipeScene} />
      <div className="relative"><button onClick={() => setAddOpen(value => !value)} className="w-full rounded bg-accent-blue px-2.5 py-2 text-xs text-white flex items-center justify-center gap-1"><Plus size={13} /> Add layer</button>{addOpen && <div className="absolute z-[1100] mt-1 max-h-[75vh] w-full space-y-1 overflow-y-auto rounded border border-border bg-bg-primary p-1 shadow-xl"><button onClick={addCamera} className="w-full rounded px-2 py-1.5 text-left text-[11px] text-cyan-200 hover:bg-bg-hover">Add camera</button><div className="px-2 pt-1 text-[8px] font-medium uppercase tracking-wider text-text-muted">Atmospheric effect · 14 presets</div><div className="grid grid-cols-2 gap-1">{ATMOSPHERE_KINDS.map(kind => <button key={kind} onClick={() => addAtmosphere(kind)} title={`${ATMOSPHERE_LABELS[kind]} — ${ATMOSPHERE_DESCRIPTIONS[kind]}`} className="truncate rounded border border-border px-2 py-1.5 text-left text-[9px] text-purple-200 hover:border-purple-400/60 hover:bg-bg-hover">{ATMOSPHERE_LABELS[kind]}</button>)}</div><button onClick={() => { setPicker('model'); setAddOpen(false) }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Select generated 3D model</button><button onClick={() => { setAddOpen(false); modelInputRef.current?.click() }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Import GLB</button><button onClick={() => { setPicker('media'); setAddOpen(false) }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Select generated image/video</button><button onClick={() => { setAddOpen(false); mediaInputRef.current?.click() }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Import image/video</button><button onClick={() => { setAddOpen(false); overlayInputRef.current?.click() }} className="w-full rounded px-2 py-1.5 text-left text-[11px] hover:bg-bg-hover">Import transparent PNG/WebP</button></div>}</div>
      {picker && <div className="rounded border border-border bg-bg-primary p-2"><div className="mb-1 flex justify-between text-[10px] text-text-muted"><span>{picker === 'model' ? 'Generated 3D models' : 'Generated images & videos'}</span><button onClick={() => setPicker(null)}><Down size={13} /></button></div><div className="grid grid-cols-3 gap-1.5 max-h-40 overflow-y-auto">{(picker === 'model' ? generatedModels : generatedMedia).map(asset => <button key={asset.name} onClick={() => addLayer(asset.type === 'model3d' ? 'model3d' : asset.type === 'video' ? 'video' : 'image', asset.url, asset.name, asset.thumbnail_url ?? undefined)} className="overflow-hidden rounded border border-border text-left hover:border-accent-blue"><div className="aspect-square bg-bg-active">{asset.thumbnail_url || asset.type === 'image' ? <img src={asset.thumbnail_url ?? asset.url} alt="" className="h-full w-full object-cover" /> : <div className="h-full flex items-center justify-center"><Video size={16} /></div>}</div><span className="block truncate px-1 py-1 text-[9px]">{asset.name}</span></button>)}</div></div>}
      <input ref={modelInputRef} type="file" accept=".glb,model/gltf-binary" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) addOrReassign('model3d', file) }} /><input ref={mediaInputRef} type="file" accept="image/*,video/*" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) addOrReassign(file.type.startsWith('video/') ? 'video' : 'image', file) }} /><input ref={overlayInputRef} type="file" accept="image/png,image/webp" multiple className="hidden" onChange={event => [...(event.target.files ?? [])].forEach(file => addOrReassign('overlay', file))} />
      <div><div className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-text-muted">Layers</div><div className="space-y-1">{[...scene.layers].sort((a, b) => b.z - a.z).map(layer => <div key={layer.id} onClick={() => setSelectedId(layer.id)} className={`flex cursor-pointer items-center gap-1.5 rounded border p-1.5 text-[10px] ${selectedId === layer.id ? 'border-accent-blue bg-accent-blue/10' : 'border-border bg-bg-primary'}`}><div className="h-7 w-7 shrink-0 overflow-hidden rounded bg-bg-active flex items-center justify-center">{layer.thumbnail ? <img src={layer.thumbnail} alt="" className="h-full w-full object-cover" /> : iconFor(layer.type)}</div><div className="min-w-0 flex-1"><div className="truncate">{layer.name}</div><div className="text-[9px] text-text-muted">{layer.type} · z: {layer.z}{layer.missingAsset ? ' · missing asset' : ''}</div></div><button onClick={event => { event.stopPropagation(); updateLayer(layer.id, item => ({ ...item, visible: !item.visible })) }} title="Visibility">{layer.visible ? <Eye size={12} /> : <EyeOff size={12} />}</button><div className="flex flex-col"><button title="Bring forward" onClick={event => { event.stopPropagation(); moveLayerZ(layer.id, 1) }}><ChevronUp size={12} /></button><button title="Send backward" onClick={event => { event.stopPropagation(); moveLayerZ(layer.id, -1) }}><ChevronDown size={12} /></button></div><button onClick={event => { event.stopPropagation(); updateScene(current => ({ ...current, layers: normalizeZ(current.layers.filter(item => item.id !== layer.id)) })); if (selectedId === layer.id) setSelectedId(null) }} className="text-red-400"><Trash2 size={12} /></button></div>)}</div></div>
      {selected && <label className={`flex cursor-pointer items-center justify-between gap-2 rounded border p-2 text-[9px] ${chainFromPlayhead ? 'border-purple-300/60 bg-purple-400/10 text-purple-100' : 'border-border bg-bg-primary text-text-secondary'}`}><span><span className="block font-medium">Chain preset from playhead</span><span className="block text-[8px] text-text-muted">Starts on frame {Math.round(progress * scene.duration * fps)} from the exact current transform.</span></span><input type="checkbox" checked={chainFromPlayhead} onChange={event => setChainFromPlayhead(event.target.checked)} /></label>}
      {selected && <div className="grid grid-cols-2 gap-1.5"><button type="button" onClick={() => updateLayer(selected.id, layer => ({ ...layer, locked: !layer.locked }))} className={`flex items-center justify-center gap-1 rounded border py-1.5 text-[9px] ${selected.locked ? 'border-amber-400/60 bg-amber-400/10 text-amber-200' : 'border-border bg-bg-primary text-text-secondary'}`}>{selected.locked ? <Lock size={11} /> : <Unlock size={11} />}{selected.locked ? 'Locked' : 'Lock layer'}</button><button type="button" onClick={() => duplicateLayer(selected.id)} className="flex items-center justify-center gap-1 rounded border border-border bg-bg-primary py-1.5 text-[9px] text-text-secondary"><CopyPlus size={11} /> Duplicate</button>{selected.locked && <p className="col-span-2 text-[8px] text-amber-200/80">Unlock this layer to change transforms, timing, presets or keyframes.</p>}</div>}
      {selected?.type === 'camera' && <div className="space-y-2 border-t border-border pt-3">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium uppercase tracking-wider text-text-muted">Camera inspector</span><span className={`rounded px-1.5 py-0.5 text-[8px] ${activeCamera?.id === selected.id ? 'bg-cyan-400/15 text-cyan-200' : 'bg-bg-active text-text-muted'}`}>{activeCamera?.id === selected.id ? 'Active camera' : 'Inactive'}</span></div>
        <label className="text-[10px] text-text-muted">Name<input value={selected.name} onChange={event => updateLayer(selected.id, layer => ({ ...layer, name: event.target.value }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs" /></label>
        <label className="flex items-center gap-1.5 text-[10px] text-text-secondary"><input type="checkbox" checked={selected.visible} onChange={event => setLayerVisibility(selected.id, event.target.checked)} /> Use this camera</label>
        <div className="grid grid-cols-2 gap-1.5">
          {numberInput('Pan X', selected.transform.x, value => updateCameraTransform(selected.id, 'x', value), -100, 200, .5)}
          {numberInput('Pan Y', selected.transform.y, value => updateCameraTransform(selected.id, 'y', value), -100, 200, .5)}
          {numberInput('Zoom', selected.transform.scale, value => updateCameraTransform(selected.id, 'scale', Math.max(.05, value)), .05, 5, .05)}
          {numberInput('Rotation', selected.transform.rotation ?? 0, value => updateCameraTransform(selected.id, 'rotation', value), -360, 360, .5)}
          {numberInput('Z / priority', selected.z, value => updateLayer(selected.id, layer => ({ ...layer, z: value })))}
        </div>
        <div className="space-y-1.5"><div className="flex items-center justify-between"><span className="text-[10px] font-medium text-text-secondary">Camera shots</span><span className="text-[9px] text-text-muted">Click again to remove</span></div><div className="grid grid-cols-2 gap-1">{CAMERA_PRESETS.map(preset => <button key={preset.id} onClick={() => selectedPresetId === preset.id ? removeLayerMotionPreset() : applyCameraPreset(preset.id)} className={`rounded border px-2 py-1.5 text-left text-[9px] ${selectedPresetId === preset.id ? 'border-cyan-300 bg-cyan-400/10 text-cyan-200' : 'border-border bg-bg-primary text-text-secondary hover:border-cyan-400/60'}`}>{preset.label}</button>)}</div></div>
        <div className="grid grid-cols-2 gap-1.5">{(['start', 'end'] as const).map(key => <div key={key} className="space-y-1"><div className="text-[10px] capitalize text-text-muted">{key} camera</div>{numberInput('X', selected.animation[key].x, value => updateLayerEndpoint(selected.id, key, { x: value }))}{numberInput('Y', selected.animation[key].y, value => updateLayerEndpoint(selected.id, key, { y: value }))}{numberInput('Zoom', selected.animation[key].scale, value => updateLayerEndpoint(selected.id, key, { scale: Math.max(.05, value) }), .05, 5, .05)}{numberInput('Rotation', selected.animation[key].rotation ?? selected.transform.rotation ?? 0, value => updateLayerEndpoint(selected.id, key, { rotation: value }), -360, 360, .5)}</div>)}</div>
        <div className="grid grid-cols-2 gap-1.5">{numberInput('Duration (s)', selected.animation.duration, value => updateLayerDuration(selected.id, value), .1, 30, .05)}<label className="text-[10px] text-text-muted">All segment curves<select value={selected.animation.curve} onChange={event => updateLayerCurve(selected.id, event.target.value as SceneCurve)} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs"><option value="linear">Linear</option><option value="ease">Ease</option><option value="dramatic">Dramatic</option><option value="bounce">Bounce</option><option value="hold">Hold / cutout</option></select></label></div>
        <div className="space-y-1.5 rounded border border-border bg-bg-primary p-2">
          <label className="flex items-center gap-1.5 text-[10px] text-text-secondary"><input type="checkbox" checked={Boolean(selected.animation.shake?.amount)} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, shake: event.target.checked ? { amount: layer.animation.shake?.amount || .35, frequency: layer.animation.shake?.frequency ?? 2, seed: layer.animation.shake?.seed ?? 1 } : undefined } }))} /> Camera shake (intentional)</label>
          {Boolean(selected.animation.shake?.amount) && <div className="grid grid-cols-2 gap-1.5">{numberInput('Shake amount', selected.animation.shake?.amount ?? .35, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, shake: { amount: Math.max(.01, Math.min(8, value)), frequency: layer.animation.shake?.frequency ?? 2, seed: layer.animation.shake?.seed ?? 1 } } })), .01, 8, .05)}{numberInput('Shake Hz', selected.animation.shake?.frequency ?? 2, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, shake: { amount: layer.animation.shake?.amount ?? .35, frequency: Math.max(.1, Math.min(30, value)), seed: layer.animation.shake?.seed ?? 1 } } })), .1, 30, .1)}</div>}
          <p className="text-[8px] text-text-muted">Shake is opt-in. Photo motion presets are smooth by default; camera shots marked “shake” enable it deliberately.</p>
        </div>
        <p className="text-[9px] text-text-muted">The highest visible camera is active. Its pan, zoom and rotation are applied identically to preview and WebM capture.</p>
      </div>}
      {selected?.type === 'image' && <button type="button" onClick={sendImageToPanoramaLoop} className="w-full rounded border border-amber-300/45 bg-amber-400/10 px-2 py-1.5 text-[10px] text-amber-100">Create infinite background from selected image</button>}
      {selected?.type === 'image' && selected.seamlessHorizontal && <button type="button" onClick={() => setCylinderCompareOpen(value => !value)} className="w-full rounded border border-cyan-300/40 bg-cyan-400/[.06] px-2 py-1.5 text-[10px] text-cyan-100">{cylinderCompareOpen ? 'Hide cylinder comparison' : 'Compare parallax vs cylinder'}</button>}
      {selected?.type === 'image' && !selected.seamlessHorizontal && <p className="rounded border border-cyan-300/15 bg-cyan-400/[.025] px-2 py-1.5 text-[8px] leading-relaxed text-cyan-100">Cylinder A/B is locked until this plate is marked loop-ready when mounting a narrative scene. Use Fondo infinito first; flat parallax remains the safe renderer.</p>}
      {selected?.type === 'image' && cylinderCompareOpen && <CylinderPanoramaComparison source={selected.source} onClose={() => setCylinderCompareOpen(false)} />}
      {selected?.type !== 'camera' && <>
      {selected ? <div className="border-t border-border pt-3 space-y-2"><div className="text-[10px] font-medium uppercase tracking-wider text-text-muted">Layer inspector</div>{selected.missingAsset && <button onClick={() => { setReassignId(selected.id); (selected.type === 'model3d' ? modelInputRef : selected.type === 'overlay' ? overlayInputRef : mediaInputRef).current?.click() }} className="w-full rounded border border-red-400/50 py-1.5 text-[10px] text-red-300">Reassign missing asset</button>}<label className="text-[10px] text-text-muted">Name<input value={selected.name} onChange={event => updateLayer(selected.id, layer => ({ ...layer, name: event.target.value }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs" /></label><div className="grid grid-cols-3 gap-1.5">{numberInput('X', selected.transform.x, value => { const delta = value - selected.transform.x; updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, x: value }, animation: { ...layer.animation, start: { ...layer.animation.start, x: layer.animation.start.x + delta }, end: { ...layer.animation.end, x: layer.animation.end.x + delta } } })); flashAt(value, selected.transform.y) }, -100, 200)}{numberInput('Y', selected.transform.y, value => { const delta = value - selected.transform.y; updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, y: value }, animation: { ...layer.animation, start: { ...layer.animation.start, y: layer.animation.start.y + delta }, end: { ...layer.animation.end, y: layer.animation.end.y + delta } } })); flashAt(selected.transform.x, value) }, -100, 200)}{numberInput('Z', selected.z, value => updateLayer(selected.id, layer => ({ ...layer, z: value })))}{numberInput('Scale', selected.transform.scale, value => updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, scale: value }, animation: { ...layer.animation, start: { ...layer.animation.start, scale: value }, end: { ...layer.animation.end, scale: value } } })), .05, 3, .05)}{numberInput('Opacity', selected.transform.opacity, value => updateLayer(selected.id, layer => ({ ...layer, transform: { ...layer.transform, opacity: value }, animation: { ...layer.animation, start: { ...layer.animation.start, opacity: value }, end: { ...layer.animation.end, opacity: value } } })), 0, 1, .05)}{numberInput('Rotation', selected.transform.rotation ?? 0, value => updateLayer(selected.id, layer => { const previous = layer.transform.rotation ?? 0; const delta = value - previous; return { ...layer, transform: { ...layer.transform, rotation: value }, animation: { ...layer.animation, start: { ...layer.animation.start, rotation: layer.animation.start.rotation === undefined ? undefined : layer.animation.start.rotation + delta }, end: { ...layer.animation.end, rotation: layer.animation.end.rotation === undefined ? undefined : layer.animation.end.rotation + delta } } } }), -360, 360)} </div><label className="flex items-center gap-1.5 text-[10px] text-text-secondary"><input type="checkbox" checked={selected.visible} onChange={event => updateLayer(selected.id, layer => ({ ...layer, visible: event.target.checked }))} /> Visible</label><div className="space-y-1.5 rounded border border-fuchsia-400/30 bg-fuchsia-400/[.04] p-2"><div className="flex items-center justify-between"><span className="text-[10px] font-medium text-fuchsia-100">Instruct {selected.name}</span><span className="text-[8px] text-fuchsia-200/80">This item only</span></div><p className="text-[8px] leading-relaxed text-text-muted">Describe a change for this selected layer. The copilot proposes a reversible scene edit; it cannot alter other layers.</p><textarea value={copilotIntent} disabled={copilotBusy || selected.locked} onChange={event => setCopilotIntent(event.target.value)} placeholder="Move it left and make it look thoughtful…" rows={2} className="w-full resize-y rounded border border-border bg-bg-primary px-2 py-1 text-[10px] disabled:opacity-50" /><button type="button" disabled={!copilotIntent.trim() || copilotBusy || selected.locked} onClick={() => void proposeCopilotEdit()} className="w-full rounded border border-fuchsia-300/50 bg-fuchsia-400/10 px-2 py-1 text-[10px] text-fuchsia-100 disabled:opacity-40">{copilotBusy ? 'Planning edit…' : 'Propose changes'}</button>{copilotError && <p className="text-[8px] text-red-300">{copilotError}</p>}{copilotProposal && <div className="space-y-1 rounded border border-fuchsia-300/25 bg-black/15 p-1.5"><p className="text-[9px] text-fuchsia-100">{copilotProposal.summary}</p><ul className="space-y-0.5 text-[8px] text-text-secondary">{describeSceneCopilotProposal(scene, copilotProposal).map(line => <li key={line}>• {line}</li>)}</ul><div className="flex gap-1"><button type="button" onClick={applyCopilotEdit} className="flex-1 rounded bg-fuchsia-400/20 px-1.5 py-1 text-[9px] text-fuchsia-100">Apply</button><button type="button" onClick={() => setCopilotProposal(null)} className="rounded border border-border px-1.5 py-1 text-[9px] text-text-muted">Discard</button></div></div>}</div>{selected.type === 'image' && <div className="space-y-1.5 rounded border border-cyan-400/30 bg-cyan-400/[.04] p-2"><div className="flex items-center justify-between"><span className="text-[10px] font-medium text-cyan-100">Cinematic photo motion</span><span className="text-[8px] text-text-muted">One-click shot</span></div><p className="text-[8px] text-text-muted">Prepares this photograph as a full-frame background and creates or updates the active camera. Hover a card to preview the move on your photo.</p><div className="grid max-h-[390px] grid-cols-2 gap-1.5 overflow-y-auto pr-0.5">{PHOTO_MOTION_PRESETS.map(preset => <PhotoMotionPresetCard key={preset.id} preset={preset} source={selected.thumbnail ?? selected.source} scopeId={selected.id} selected={selectedPresetId === preset.id} onSelect={() => selectedPresetId === preset.id ? removePhotoMotionPreset(preset.id) : applyPhotoMotionPreset(preset.id)} />)}</div></div>}<div className="space-y-1.5"><div className="flex items-center justify-between"><span className="text-[10px] font-medium text-text-secondary">Motion presets</span><span className="text-[9px] text-text-muted">Hover to preview · click again to remove</span></div><div className="grid max-h-[370px] grid-cols-2 gap-1.5 overflow-y-auto pr-0.5">{PRESETS.map(preset => <MotionPresetCard key={preset.id} preset={preset} scopeId={selected.id} selected={selectedPresetId === preset.id} onSelect={() => { if (selectedPresetId === preset.id) removeLayerMotionPreset(); else { setSelectedPresetId(preset.id); applyPreset(preset.id) } }} />)}</div></div><div className="grid grid-cols-2 gap-1.5">{(['start', 'end'] as const).map(key => <div key={key} className="space-y-1"><div className="text-[10px] text-text-muted capitalize">{key} motion</div>{numberInput('X', selected.animation[key].x, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, [key]: { ...layer.animation[key], x: value } } })))}{numberInput('Y', selected.animation[key].y, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, [key]: { ...layer.animation[key], y: value } } })))}{numberInput('Scale', selected.animation[key].scale, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, [key]: { ...layer.animation[key], scale: value } } })), .05, 3, .05)}</div>)}</div><div className="grid grid-cols-2 gap-1.5">{numberInput('Duration (s)', selected.animation.duration, value => updateLayerDuration(selected.id, value, 1), 1, 30)}<label className="text-[10px] text-text-muted">Curve<select value={selected.animation.curve} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, curve: event.target.value as SceneCurve } }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs"><option value="linear">Linear</option><option value="ease">Ease</option><option value="dramatic">Dramatic</option><option value="bounce">Bounce</option></select></label></div>{selected.type === 'model3d' && <div className="grid grid-cols-2 gap-1.5"><label className="flex items-end gap-1.5 pb-1 text-[10px]"><input type="checkbox" checked={Boolean(selected.animation.spin)} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, spin: event.target.checked } }))} /> Auto spin</label>{numberInput('Spin °/sec', selected.animation.rotationSpeed ?? 35, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, rotationSpeed: value } })), 0, 720)}</div>}{selected.type === 'model3d' && (clipsByLayer[selected.id]?.length ?? 0) > 0 && <div className="space-y-2 rounded border border-emerald-400/30 bg-emerald-400/[.04] p-2"><label className="text-[10px] text-text-muted">Skeletal animation<select value={selected.animation.clip ?? ''} disabled={selected.locked} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, clip: event.target.value || undefined, clipOffset: layer.animation.clipOffset ?? 0, clipSpeed: layer.animation.clipSpeed ?? 1, clipLoop: layer.animation.clipLoop ?? true, clipReverse: layer.animation.clipReverse ?? false, clipTrimStart: 0, clipTrimEnd: undefined } }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs disabled:opacity-50"><option value="">Off</option>{(clipsByLayer[selected.id] ?? []).map(clip => <option key={clip} value={clip}>{clip}</option>)}</select></label>{selected.animation.clip && <><div className="grid grid-cols-2 gap-1.5">{numberInput('Clip offset', selected.animation.clipOffset ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, clipOffset: value } })), 0, scene.duration, 1 / fps, selected.locked)}{numberInput('Clip speed', selected.animation.clipSpeed ?? 1, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, clipSpeed: value } })), .05, 8, .05, selected.locked)}{numberInput('Clip trim in', selected.animation.clipTrimStart ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, clipTrimStart: value, clipTrimEnd: layer.animation.clipTrimEnd !== undefined && layer.animation.clipTrimEnd <= value ? value + .001 : layer.animation.clipTrimEnd } })), 0, Math.max(0, (selectedClipDuration || 3600) - .001), 1 / fps, selected.locked)}{numberInput('Clip trim out', selected.animation.clipTrimEnd ?? selectedClipDuration, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, clipTrimEnd: Math.max((layer.animation.clipTrimStart ?? 0) + .001, value) } })), .001, selectedClipDuration || 3600, 1 / fps, selected.locked)}</div><div className="flex flex-wrap gap-3 text-[9px] text-text-secondary"><label className="flex items-center gap-1"><input type="checkbox" checked={selected.animation.clipLoop !== false} disabled={selected.locked} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, clipLoop: event.target.checked } }))} /> Loop clip</label><label className="flex items-center gap-1"><input type="checkbox" checked={Boolean(selected.animation.clipReverse)} disabled={selected.locked} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, clipReverse: event.target.checked } }))} /> Reverse</label><button type="button" disabled={selected.locked} onClick={() => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, clipTrimStart: 0, clipTrimEnd: undefined } }))} className="ml-auto text-[8px] text-emerald-200 disabled:opacity-40">Full clip</button></div><p className="text-[8px] text-text-muted">{selectedClipDuration > 0 ? `Clip length ${selectedClipDuration.toFixed(2)}s.` : 'Reading clip length…'} Scrub, preview and WebM use the same paused-frame sampler.</p></>}</div>}</div> : <p className="text-[10px] text-text-muted">Select a layer to edit it.</p>}
      {selected && <button type="button" disabled={copilotBusy || selected.locked || copilotListening} onClick={dictateCopilotIntent} className="flex w-full items-center justify-center gap-1 rounded border border-fuchsia-300/35 bg-fuchsia-400/[.04] px-2 py-1 text-[9px] text-fuchsia-100 disabled:opacity-40"><Mic size={11} />{copilotListening ? 'Listening for this item…' : `Dictate instruction for ${selected.name}`}</button>}
      {selected?.type === 'effect' && selectedAtmosphere && <div className="space-y-2 rounded border border-purple-400/30 bg-purple-400/[.04] p-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-purple-100">Atmospheric particles</span><span className="text-[8px] text-text-muted">Preview + WebM</span></div>
        <p className="text-[8px] text-purple-100/70">{ATMOSPHERE_DESCRIPTIONS[selectedAtmosphere.kind]}</p>
        <label className="text-[9px] text-text-muted">Effect<select value={selectedAtmosphere.kind} disabled={selected.locked} onChange={event => { const kind = event.target.value as SceneAtmosphereKind; updateLayer(selected.id, layer => ({ ...layer, name: ATMOSPHERE_LABELS[kind], source: `maestro-effect:${kind}`, atmosphere: { ...ATMOSPHERE_PRESETS[kind] } })) }} className="mt-0.5 w-full rounded border border-border bg-bg-tertiary px-2 py-1 text-[10px] disabled:opacity-50">{ATMOSPHERE_KINDS.map(kind => <option key={kind} value={kind}>{ATMOSPHERE_LABELS[kind]}</option>)}</select></label>
        <div className="grid grid-cols-2 gap-1.5">
          {numberInput('Density', selectedAtmosphere.density, value => updateLayer(selected.id, layer => ({ ...layer, atmosphere: { ...normalizedAtmosphere(layer.atmosphere), density: Math.round(value) } })), 5, 240, 1, selected.locked)}
          {numberInput('Speed', selectedAtmosphere.speed, value => updateLayer(selected.id, layer => ({ ...layer, atmosphere: { ...normalizedAtmosphere(layer.atmosphere), speed: value } })), .05, 4, .05, selected.locked)}
          {numberInput('Particle size', selectedAtmosphere.size, value => updateLayer(selected.id, layer => ({ ...layer, atmosphere: { ...normalizedAtmosphere(layer.atmosphere), size: value } })), .2, 8, .05, selected.locked)}
          {numberInput('Wind', selectedAtmosphere.wind, value => updateLayer(selected.id, layer => ({ ...layer, atmosphere: { ...normalizedAtmosphere(layer.atmosphere), wind: value } })), -100, 100, 1, selected.locked)}
        </div>
        <label className="flex items-center justify-between gap-2 text-[9px] text-text-muted">Particle color<input type="color" value={selectedAtmosphere.color} disabled={selected.locked} onChange={event => updateLayer(selected.id, layer => ({ ...layer, atmosphere: { ...normalizedAtmosphere(layer.atmosphere), color: event.target.value } }))} className="h-7 w-12 rounded border border-border bg-bg-tertiary disabled:opacity-50" /></label>
        <p className="text-[8px] text-text-muted">Particles are deterministic: scrubbing, playback and recording show the same frame. Use layer opacity and Z to blend the effect into the shot.</p>
      </div>}
      {selected && isVisualLayer(selected) && selected.type !== 'effect' && <div className="space-y-2 rounded border border-border bg-bg-primary p-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-text-secondary">Camera parallax</span><span className="text-[9px] text-text-muted">Z order unchanged</span></div>
        <div className="grid grid-cols-3 gap-1">{(['background', 'midground', 'foreground'] as const).map(preset => <button key={preset} onClick={() => applyParallaxPreset(selected.id, preset)} className={`rounded border px-1 py-1.5 text-[8px] capitalize ${Math.abs((selected.parallax ?? 1) - PARALLAX_PRESETS[preset]) < .001 ? 'border-cyan-300 bg-cyan-400/10 text-cyan-200' : 'border-border text-text-muted hover:border-cyan-400/60'}`}>{preset}</button>)}</div>
        {numberInput('Parallax strength', selected.parallax ?? 1, value => updateLayer(selected.id, layer => ({ ...layer, parallax: Math.max(0, Math.min(2, value)) })), 0, 2, .05)}
        <p className="text-[9px] text-text-muted">0 ignores camera pan, 1 follows it normally, and values above 1 feel closer. Zoom and camera roll still affect the full shot. Background adds 20% overscan to image/video layers; extreme moves may need more scale.</p>
      </div>}
      {selected && selectedEffects && <div className="space-y-2 rounded border border-border bg-bg-primary p-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-text-secondary">Layer effects & mask</span><button type="button" disabled={selected.locked} onClick={() => updateLayer(selected.id, layer => ({ ...layer, effects: undefined }))} className="text-[8px] text-text-muted hover:text-text-primary disabled:opacity-40">Reset</button></div>
        <div className="grid grid-cols-2 gap-1.5">
          <label className="text-[9px] text-text-muted">Blend<select value={selectedEffects.blendMode} disabled={selected.locked} onChange={event => updateLayerEffects(selected.id, { blendMode: event.target.value as SceneBlendMode })} className="mt-0.5 w-full rounded border border-border bg-bg-tertiary px-1.5 py-1 text-[10px] disabled:opacity-50"><option value="normal">Normal</option><option value="screen">Screen</option><option value="multiply">Multiply</option><option value="overlay">Overlay</option><option value="lighten">Lighten</option><option value="darken">Darken</option></select></label>
          <label className="text-[9px] text-text-muted">Mask<select value={selectedEffects.mask} disabled={selected.locked} onChange={event => updateLayerEffects(selected.id, { mask: event.target.value as SceneMask })} className="mt-0.5 w-full rounded border border-border bg-bg-tertiary px-1.5 py-1 text-[10px] disabled:opacity-50"><option value="none">Rectangle</option><option value="rounded">Rounded</option><option value="ellipse">Ellipse</option></select></label>
        </div>
        {selectedEffects.mask === 'rounded' && numberInput('Corner radius %', selectedEffects.maskRadius, value => updateLayerEffects(selected.id, { maskRadius: value }), 0, 50, 1, selected.locked)}
        <div className="grid grid-cols-2 gap-1.5">{numberInput('Blur %', selectedEffects.blur, value => updateLayerEffects(selected.id, { blur: value }), 0, 3, .05, selected.locked)}{numberInput('Glow %', selectedEffects.glow, value => updateLayerEffects(selected.id, { glow: value }), 0, 5, .05, selected.locked)}{numberInput('Shadow %', selectedEffects.shadow, value => updateLayerEffects(selected.id, { shadow: value }), 0, 8, .1, selected.locked)}{numberInput('Brightness', selectedEffects.brightness, value => updateLayerEffects(selected.id, { brightness: value }), 0, 3, .05, selected.locked)}{numberInput('Contrast', selectedEffects.contrast, value => updateLayerEffects(selected.id, { contrast: value }), 0, 3, .05, selected.locked)}{numberInput('Saturation', selectedEffects.saturation, value => updateLayerEffects(selected.id, { saturation: value }), 0, 4, .05, selected.locked)}{numberInput('Hue °', selectedEffects.hue, value => updateLayerEffects(selected.id, { hue: value }), -180, 180, 1, selected.locked)}</div>
        <p className="text-[8px] text-text-muted">Percent effects scale from the frame’s short side, so preview, saved thumbnail and WebM stay visually aligned. Effects are clipped to the layer box or selected mask.</p>
      </div>}
      {selected && selectedStrip && <div className="space-y-2 rounded border border-fuchsia-400/30 bg-fuchsia-400/[.04] p-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-fuchsia-100">Infinite strip</span><label className="flex items-center gap-1 text-[9px] text-text-secondary"><input type="checkbox" checked={selectedStrip.enabled} disabled={selected.locked} onChange={event => updateLayer(selected.id, layer => ({ ...layer, strip: { ...normalizedStrip(layer.strip), enabled: event.target.checked } }))} /> Enabled</label></div>
        <p className="text-[8px] text-text-muted">Repeats this layer in a seamless moving row or column. It works with transparent 2D assets, video and GLB.</p>
        <div className="grid grid-cols-2 gap-1.5">
          {numberInput('Copies', selectedStrip.count, value => updateLayer(selected.id, layer => ({ ...layer, strip: { ...normalizedStrip(layer.strip), count: Math.round(value) } })), 1, 12, 1, selected.locked)}
          {numberInput('Spacing %', selectedStrip.spacing, value => updateLayer(selected.id, layer => ({ ...layer, strip: { ...normalizedStrip(layer.strip), spacing: value } })), 2, 200, 1, selected.locked)}
          {numberInput('Speed %/s', selectedStrip.speed, value => updateLayer(selected.id, layer => ({ ...layer, strip: { ...normalizedStrip(layer.strip), speed: value } })), 0, 300, 1, selected.locked)}
          {numberInput('Start phase %', selectedStrip.phase, value => updateLayer(selected.id, layer => ({ ...layer, strip: { ...normalizedStrip(layer.strip), phase: value } })), -1000, 1000, 1, selected.locked)}
        </div>
        <label className="text-[9px] text-text-muted">Direction<select value={selectedStrip.direction} disabled={selected.locked} onChange={event => updateLayer(selected.id, layer => ({ ...layer, strip: { ...normalizedStrip(layer.strip), direction: event.target.value as LayerStrip['direction'] } }))} className="mt-0.5 w-full rounded border border-border bg-bg-tertiary px-2 py-1 text-[10px] disabled:opacity-50"><option value="down">Top → bottom</option><option value="up">Bottom → top</option><option value="right">Left → right</option><option value="left">Right → left</option></select></label>
        <label className="text-[9px] text-text-muted">Seam cover<select value={selectedStrip.seamOccluder.enabled ? selectedStrip.seamOccluder.kind : 'off'} disabled={selected.locked || !selectedStrip.enabled} onChange={event => updateLayer(selected.id, layer => ({ ...layer, strip: { ...normalizedStrip(layer.strip), seamOccluder: { ...normalizedStrip(layer.strip).seamOccluder, enabled: event.target.value !== 'off', kind: event.target.value === 'off' ? normalizedStrip(layer.strip).seamOccluder.kind : event.target.value as SeamOccluderKind } } }))} className="mt-0.5 w-full rounded border border-border bg-bg-tertiary px-2 py-1 text-[10px] disabled:opacity-50"><option value="off">Off</option><option value="pole">Pole / post</option><option value="lamp">Lamp</option><option value="tree">Tree</option><option value="column">Column</option></select></label>
        {selectedStrip.seamOccluder.enabled && <><>{numberInput('Cover scale', selectedStrip.seamOccluder.scale, value => updateLayer(selected.id, layer => ({ ...layer, strip: { ...normalizedStrip(layer.strip), seamOccluder: { ...normalizedStrip(layer.strip).seamOccluder, scale: value } } })), .45, 1.8, .05, selected.locked)}</>{numberInput('Cover opacity', selectedStrip.seamOccluder.opacity, value => updateLayer(selected.id, layer => ({ ...layer, strip: { ...normalizedStrip(layer.strip), seamOccluder: { ...normalizedStrip(layer.strip).seamOccluder, opacity: value } } })), .2, 1, .05, selected.locked)}</>}
        <p className="text-[8px] text-text-muted">A foreground silhouette stays locked to each tile join so a looping plate never shows its seam.</p>
        {selected.type === 'model3d' && selectedStrip.count > 4 && <p className="text-[8px] text-amber-200">Preview caps GLB copies at 4. Extra copies freeze the GPU.</p>}
      </div>}
      </>}
      {selected && <div className="space-y-2 rounded border border-border bg-bg-primary p-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-text-secondary">Layer relationship</span><span className="text-[8px] text-text-muted">2D scene space</span></div>
        <label className="text-[9px] text-text-muted">Behaviour<select value={selected.relationship?.type ?? 'none'} disabled={selected.locked} onChange={event => setLayerRelationship(event.target.value as NonNullable<AnimatorLayer['relationship']>['type'] | 'none')} className="mt-0.5 w-full rounded border border-border bg-bg-tertiary px-2 py-1 text-[10px] disabled:opacity-50"><option value="none">Independent</option>{selected.type !== 'camera' && <option value="parent">Parent / child</option>}<option value="follow">Follow layer</option>{selected.type !== 'camera' && <option value="lookAt">Look at layer</option>}</select></label>
        {selected.relationship && <>
          <label className="text-[9px] text-text-muted">Target<select value={selected.relationship.targetLayerId} disabled={selected.locked} onChange={event => setRelationshipTarget(event.target.value)} className="mt-0.5 w-full rounded border border-border bg-bg-tertiary px-2 py-1 text-[10px] disabled:opacity-50">{relationshipTargets.map(layer => <option key={layer.id} value={layer.id}>{layer.name} · {layer.type}</option>)}</select></label>
          {selected.relationship.type === 'follow' && <div className="grid grid-cols-3 gap-1">{numberInput('Offset X', selected.relationship.offsetX ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, relationship: layer.relationship ? { ...layer.relationship, offsetX: value } : undefined })), -200, 200, .5)}{numberInput('Offset Y', selected.relationship.offsetY ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, relationship: layer.relationship ? { ...layer.relationship, offsetY: value } : undefined })), -200, 200, .5)}{numberInput('Strength', selected.relationship.strength ?? 1, value => updateLayer(selected.id, layer => ({ ...layer, relationship: layer.relationship ? { ...layer.relationship, strength: Math.max(0, Math.min(1, value)) } : undefined })), 0, 1, .05)}</div>}
          {selected.relationship.type === 'lookAt' && numberInput('Angle offset', selected.relationship.rotationOffset ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, relationship: layer.relationship ? { ...layer.relationship, rotationOffset: value } : undefined })), -360, 360, 1)}
          <p className="text-[8px] text-text-muted">{selected.relationship.type === 'parent' ? 'Inherits the target movement, scale and rotation while preserving this layer’s own animation.' : selected.relationship.type === 'follow' ? 'Blends toward the target plus the stored offset. Camera follow keeps the subject framed.' : 'Rotates this layer so it faces the target in the current output aspect ratio.'}</p>
        </>}
      </div>}
      {selected && isVisualLayer(selected) && selected.animation.orbit && <div className="rounded border border-accent-blue/40 bg-accent-blue/10 p-2 space-y-2">
        <div className="flex items-center justify-between"><span className="text-[10px] font-medium text-accent-blue">Relational orbit</span><button onClick={() => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: undefined } }))} className="text-[9px] text-text-muted hover:text-red-400">Remove</button></div>
        <label className="text-[10px] text-text-muted">Orbit around<select value={selected.animation.orbit.targetLayerId} disabled={selected.locked} onChange={event => setOrbitTarget(event.target.value)} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs disabled:opacity-50">{scene.layers.filter(layer => layer.id !== selected.id && isVisualLayer(layer) && !dependencyWouldCycle(selected.id, layer.id)).map(layer => <option key={layer.id} value={layer.id}>{layer.name} · {layer.type}</option>)}</select></label>
        <div className="grid grid-cols-2 gap-1.5">{numberInput('Horizontal radius', selected.animation.orbit.radiusX, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, radiusX: Math.max(0, value) } : undefined } })), 0, 100, 1)}{numberInput('Vertical radius', selected.animation.orbit.radiusY, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, radiusY: Math.max(0, value) } : undefined } })), 0, 100, 1)}{numberInput('Orbit copies', selected.animation.orbit.count ?? 1, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, count: Math.round(value) } : undefined } })), 1, 12, 1)}{numberInput('Turns', selected.animation.orbit.turns, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, turns: value } : undefined } })), -20, 20, .25)}{numberInput('Center offset X', selected.animation.orbit.centerOffsetX ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, centerOffsetX: value } : undefined } })), -100, 100, .5)}{numberInput('Center offset Y', selected.animation.orbit.centerOffsetY ?? 0, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, centerOffsetY: value } : undefined } })), -100, 100, .5)}{numberInput('Start phase °', selected.animation.orbit.phase, value => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, phase: value } : undefined } })), -360, 360, 5)}<label className="text-[10px] text-text-muted">Facing<select value={selected.animation.orbit.facing ?? 'fixed'} disabled={selected.locked} onChange={event => updateLayer(selected.id, layer => ({ ...layer, animation: { ...layer.animation, orbit: layer.animation.orbit ? { ...layer.animation.orbit, facing: event.target.value as NonNullable<NonNullable<AnimatorLayer['animation']['orbit']>['facing']> } : undefined } }))} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs disabled:opacity-50"><option value="fixed">Fixed direction</option><option value="center">Face center</option><option value="outward">Face outward</option></select></label></div>
        <p className="text-[9px] text-text-muted">The cyan cross marks the exact orbit center. Use center offsets when an asymmetric GLB's visual center differs from its layer box. Negative turns reverse direction.</p>
      </div>}
      <div className="border-t border-border pt-3 space-y-2">
        <div className="grid grid-cols-2 gap-1.5">
          <button disabled={!selected} onClick={() => selected && navigator.clipboard.writeText(JSON.stringify({ version: 1, motion: motion(selected) }, null, 2)).then(() => setMessage('Movement JSON copied.'))} className="rounded border border-border bg-bg-primary py-1.5 text-[10px] flex justify-center gap-1 disabled:opacity-40"><Copy size={11} /> Copy movement</button>
          <button onClick={() => void persistScene()} disabled={saving || !scene.layers.length} className="rounded bg-accent-blue py-1.5 text-[10px] text-white flex justify-center gap-1 disabled:opacity-40">{saving ? <Loader2 size={11} className="animate-spin" /> : <Film size={11} />} {saving ? 'Saving…' : 'Save scene'}</button>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <button onClick={exportScene} className="rounded border border-border bg-bg-primary py-1.5 text-[10px] flex justify-center gap-1"><Download size={11} /> Export scene</button>
          <button onClick={() => setLibraryOpen(true)} className="rounded border border-border bg-bg-primary py-1.5 text-[10px] flex justify-center gap-1"><FolderOpen size={11} /> Open scene</button>
        </div>
        <input ref={sceneInputRef} type="file" accept="application/json,.json" className="hidden" onChange={event => { const file = event.target.files?.[0]; event.currentTarget.value = ''; if (file) void importSceneFile(file) }} />
        <button onClick={() => setJsonOpen(value => !value)} className="w-full rounded border border-border bg-bg-primary py-1.5 text-[10px] flex justify-center gap-1"><FileJson size={11} /> {jsonOpen ? 'Close movement JSON' : 'Movement JSON tools'}</button>
        {jsonOpen && <div className="space-y-1.5"><textarea value={motionText} onChange={event => setMotionText(event.target.value)} placeholder="Paste movement JSON" rows={4} className="w-full rounded border border-border bg-bg-primary p-1.5 text-[9px] font-mono" /><div className="flex gap-1.5"><button disabled={!selected || !motionText.trim()} onClick={() => { try { applyMotion(JSON.parse(motionText.replace(/^\uFEFF/, '').trim())); setMessage('Movement applied to selected layer.') } catch (error) { setMessage(error instanceof Error ? error.message : 'Invalid motion JSON.') } }} className="rounded bg-accent-blue px-2 py-1 text-[10px] text-white disabled:opacity-40">Apply movement</button><button onClick={() => motionInputRef.current?.click()} className="rounded border border-border px-2 py-1 text-[10px]">Load movement file</button></div><input ref={motionInputRef} type="file" accept="application/json,.json" className="hidden" onChange={event => { const file = event.target.files?.[0]; event.currentTarget.value = ''; if (file) void loadMotionFile(file) }} /></div>}
        <div className="rounded border border-border bg-bg-primary p-2 text-[9px] text-text-muted whitespace-pre-wrap">Return only valid HocusPocus Scene Animator motion JSON.{`\n`}Use start/end x and y from 0 to 100, start/end scale,{`\n`}duration in seconds, curve as linear/ease/dramatic/bounce,{`\n`}and optional spin plus rotationSpeed. For multi-step motion, add keyframes with id, time, x, y, scale, opacity, rotation and curve. Optional events use id, local time, name and a plain-text payload.{`\n`}Do not include Markdown or explanations.{`\n\n`}{'{"version":1,"motion":{"start":{"x":10,"y":70,"scale":0.2},"end":{"x":90,"y":30,"scale":0.8},"duration":3,"curve":"dramatic","spin":true,"rotationSpeed":240}}'}</div>
      </div>
      {message && <p className="text-[10px] text-text-secondary">{message}</p>}
    </aside>
    <SceneLibraryDialog
      open={libraryOpen}
      workspace={workspace}
      onClose={() => setLibraryOpen(false)}
      onPickFile={() => { setLibraryOpen(false); sceneInputRef.current?.click() }}
      onOpenScene={(next, label) => {
        importScene(JSON.stringify(next), `Opened ${label}`)
        setLibraryOpen(false)
      }}
    />
  </div>
}
