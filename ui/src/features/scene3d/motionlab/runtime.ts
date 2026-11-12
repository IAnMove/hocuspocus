import { Color, Fog, type Object3D, type Scene } from 'three'
import { buildBouncingBall, buildMusicMachine } from './musicSets'
import { buildSunsetFlight, buildSeasonalCarriage, buildDataAssembly, buildLighthouseStory } from './scenic'
import { buildPosterBreakout, buildParticleMorph } from './graphicSets'
import { DEFAULT_MOTION_LAB, isMotionLab, type MotionLabHandle, type MotionLabId, type MotionLabSettings } from './types'

const BUILDERS: Record<MotionLabId, (settings: MotionLabSettings) => MotionLabHandle> = {
  'motion-bouncing-ball': buildBouncingBall, 'motion-music-machine': buildMusicMachine,
  'motion-sunset-flight': buildSunsetFlight, 'motion-seasonal-carriage': buildSeasonalCarriage,
  'motion-data-assembly': buildDataAssembly, 'motion-lighthouse-story': buildLighthouseStory,
  'motion-poster-breakout': buildPosterBreakout, 'motion-particle-morph': buildParticleMorph,
}
export function buildMotionLab(kind: string | undefined, settings?: MotionLabSettings): MotionLabHandle | null {
  if (!isMotionLab(kind)) return null
  const handle = BUILDERS[kind](settings ?? { ...DEFAULT_MOTION_LAB })
  handle.root.userData.motionLab = handle
  return handle
}
export function paintMotionLab(root: Object3D | null, seconds: number) {
  const handle = root?.userData.motionLab as MotionLabHandle | undefined
  handle?.update(seconds)
}
export function motionLabSky(kind: MotionLabId): string {
  if (kind === 'motion-sunset-flight') return '#c48097'
  if (kind === 'motion-seasonal-carriage') return '#c6dfe8'
  if (kind === 'motion-lighthouse-story') return '#25465f'
  return '#101728'
}
export function applyMotionLabAtmosphere(scene: Scene, kind: string | undefined) {
  if (!isMotionLab(kind)) return
  const color = motionLabSky(kind)
  scene.background = new Color(color)
  scene.fog = kind === 'motion-sunset-flight' || kind === 'motion-lighthouse-story' ? new Fog(color, 25, 90) : null
}
