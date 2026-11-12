import { BoxGeometry, CylinderGeometry, Group, SphereGeometry, TorusGeometry, Vector3 } from 'three'
import { musicBase, musicHandle, musicMaterial, musicMesh, poseRod } from './musicGeometry'
import { BALL_RADIUS, bouncingBallPosition, HAMMER_RADIUS, hammerHeight, KEY_DEPTH, machineKeyPosition,
  musicBeat, musicContact, musicPhase, PLATFORM_DEPTH, platformPosition } from './musicTimeline'
import type { MotionLabHandle, MotionLabSettings } from './types'

/** Orbiting ceramic platforms. Fits x/z +/-4, y 0..4.8; view from [7,7,9] toward [0,1.4,0]. */
export function buildBouncingBall(settings: MotionLabSettings): MotionLabHandle {
  const root = new Group()
  root.name = 'motion-bouncing-ball'
  musicBase(root, 4)
  const brass = musicMaterial(settings.secondaryColor, .7)
  const platform = new CylinderGeometry(.56, .62, PLATFORM_DEPTH, 28)
  const support = new CylinderGeometry(.13, .22, 1, 16)
  const rim = new TorusGeometry(.54, .025, 8, 32)
  const keys = Array.from({ length: 8 }, (_, lane) => {
    const position = platformPosition(settings, lane)
    const key = musicMesh(root, 'motion-platform-' + lane, platform, musicMaterial(settings.color), position)
    const stem = musicMesh(root, 'motion-platform-stem-' + lane, support, brass, [position[0], position[1] / 2, position[2]])
    stem.scale.y = position[1] - PLATFORM_DEPTH / 2
    musicMesh(root, 'motion-platform-rim-' + lane, rim, brass,
      [position[0], position[1] + PLATFORM_DEPTH / 2 + .035, position[2]]).rotation.x = Math.PI / 2
    return key
  })
  const ball = musicMesh(root, 'motion-ball', new SphereGeometry(BALL_RADIUS, 24, 16),
    musicMaterial(settings.secondaryColor, .65), [0, 0, 0])
  // A central spindle gives the circle a mechanical centre without hiding the contacts.
  musicMesh(root, 'motion-centre-spindle', new CylinderGeometry(.18, .35, .55, 24), brass, [0, .275, 0])
  const dial = musicMesh(root, 'motion-centre-dial', new TorusGeometry(.8, .05, 10, 40), brass, [0, .4, 0])
  dial.rotation.x = Math.PI / 2
  return musicHandle(root, seconds => {
    const beat = musicBeat(settings, seconds)
    ball.position.set(...bouncingBallPosition(settings, seconds))
    ball.rotation.set(beat * .6, beat * .35, -beat * .7)
    for (let lane = 0; lane < keys.length; lane++) {
      const since = musicPhase(beat, lane, 8) * 8
      keys[lane].material.emissiveIntensity = .025 + .65 * Math.exp(-since * 9)
    }
  })
}

function machineWheel(root: Group, settings: MotionLabSettings) {
  const wheel = new Group()
  wheel.name = 'motion-music-wheel'
  wheel.position.set(0, 2.55, -1.4)
  root.add(wheel)
  const metal = musicMaterial(settings.secondaryColor, .75)
  musicMesh(wheel, 'motion-wheel-rim', new TorusGeometry(1.22, .11, 12, 48), metal, [0, 0, 0])
  const hub = musicMesh(wheel, 'motion-wheel-hub', new CylinderGeometry(.24, .24, .36, 24), metal, [0, 0, 0])
  hub.rotation.x = Math.PI / 2
  const spoke = new BoxGeometry(.09, 1.1, .12)
  for (let index = 0; index < 8; index++) {
    const angle = index * Math.PI / 4
    musicMesh(wheel, 'motion-wheel-spoke-' + index, spoke, metal, [Math.sin(angle) * .65, Math.cos(angle) * .65, 0]).rotation.z = -angle
  }
  musicMesh(root, 'motion-wheel-stand', new BoxGeometry(.3, 2.5, .3), musicMaterial('#283a50'), [0, 1.25, -1.7])
  return wheel
}

/** Four cam-driven hammers strike solid tuned bars. Fits x +/-3.5, y 0..4.9, z +/-2.
 * Frame from [7,5.5,10] toward [0,2,0]; the front view shows every ball/bar contact and the flywheel.
 */
export function buildMusicMachine(settings: MotionLabSettings): MotionLabHandle {
  const root = new Group()
  root.name = 'motion-music-machine'
  musicBase(root, 3.9)
  const metal = musicMaterial(settings.secondaryColor, .7), dark = musicMaterial('#26354c', .6)
  const wheel = machineWheel(root, settings)
  musicMesh(root, 'motion-machine-bridge', new BoxGeometry(6.1, .18, .32), dark, [0, 4.65, 0])
  for (const side of [-1, 1]) musicMesh(root, 'motion-machine-upright-' + side,
    new CylinderGeometry(.11, .16, 4.6, 16), dark, [side * 3.15, 2.3, -.3])
  const hammerGeometry = new SphereGeometry(HAMMER_RADIUS, 20, 14)
  const rodGeometry = new CylinderGeometry(.055, .055, 1, 10)
  const parts = Array.from({ length: 4 }, (_, lane) => {
    const position = machineKeyPosition(lane)
    const note = musicContact('motion-music-machine', settings, lane)
    const key = musicMesh(root, 'motion-key-' + lane, new BoxGeometry(.95, KEY_DEPTH, 1.4 * Math.sqrt(220 / note.frequency)),
      musicMaterial(settings.color, .65), position)
    musicMesh(root, 'motion-key-pedestal-' + lane, new CylinderGeometry(.18, .28, .72, 16), dark, [position[0], .36, 0])
    const ball = musicMesh(root, 'motion-hammer-' + lane, hammerGeometry, metal, position)
    const rod = musicMesh(root, 'motion-rod-' + lane, rodGeometry, metal, position)
    const cam = musicMesh(root, 'motion-cam-' + lane, new CylinderGeometry(.2, .2, .2, 18), metal, [position[0], 4.5, 0])
    cam.rotation.x = Math.PI / 2
    return { key, ball, rod, x: position[0] }
  })
  const start = new Vector3(), end = new Vector3(), direction = new Vector3()
  return musicHandle(root, seconds => {
    const beat = musicBeat(settings, seconds)
    wheel.rotation.z = -beat * Math.PI / 2
    for (let lane = 0; lane < parts.length; lane++) {
      const part = parts[lane], phase = musicPhase(beat, lane, 4)
      part.ball.position.y = hammerHeight(settings, seconds, lane)
      start.set(part.x + .15 * Math.sin(phase * Math.PI * 2), 4.5 + .15 * Math.cos(phase * Math.PI * 2), 0)
      end.set(part.x, part.ball.position.y + HAMMER_RADIUS, 0)
      poseRod(part.rod, start, end, direction)
      part.key.material.emissiveIntensity = .025 + .7 * Math.exp(-phase * 36)
    }
  })
}
