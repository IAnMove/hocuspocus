import { Color, FogExp2, HemisphereLight, type Scene } from 'three'
import type { Scene3DDressing } from '../types.ts'
import { atmosSet, isAtmosDressing, resolveAtmos } from './registry.ts'
import type { AtmosSettings } from './params.ts'

export { atmosEye } from './eye.ts'
export { atmosFallbackLook, hasWebGL2 } from './degrade.ts'
export { parseAtmosSettings, resolveAtmos, atmosFingerprint, type AtmosSettings, type AtmosQuality, type ResolvedAtmos } from './params.ts'
export { clearingTrunks, subjectIsClear, CLEARING_SUBJECT, CLEARING_EYE, CLEARING_LOOK, BACKLIGHT_EYE, BACKLIGHT_LOOK } from './layout.ts'
export { windAt } from './wind.ts'
export { buildClearing, type AtmosHandle } from './sets/clearing.ts'
export { prepareAtmosShadows, releaseAtmosShadows, atmosHandle } from './shadows.ts'
export { atmosSet, isAtmosDressing }

function hemi(scene: Scene): HemisphereLight | undefined {
  return scene.children.find(child => child instanceof HemisphereLight) as HemisphereLight | undefined
}

export function applyAtmosAtmosphere(scene: Scene, kind: Scene3DDressing | undefined, settings?: AtmosSettings) {
  const light = hemi(scene)
  if (light && light.userData.atmosBase == null) {
    light.userData.atmosBase = light.intensity
    light.userData.atmosSky = light.color.getHex()
    light.userData.atmosGround = light.groundColor.getHex()
  }
  if (!isAtmosDressing(kind)) {
    if (light && light.userData.atmosBase != null) {
      light.intensity = light.userData.atmosBase as number
      light.color.setHex(light.userData.atmosSky as number)
      light.groundColor.setHex(light.userData.atmosGround as number)
    }
    return
  }
  if (light) {
    light.intensity = 0.34
    light.color.set(0xe7f0dc)
    light.groundColor.set(0x6d7a52)
  }
  const fog = resolveAtmos(settings, 'low', kind)
  scene.background = new Color(fog.fogColor)
  scene.fog = new FogExp2(fog.fogColor, 0.014 + fog.fogDensity * 0.034)
}
