/**
 * Renderer-agnostic projection for an equirectangular image on the inside of
 * a vertical cylinder. The cylinder axis is Y and the camera is at its centre.
 *
 * `horizontalRotation` turns the panorama around that axis and `verticalFov`
 * controls the camera ray used for the vertical coordinate. If the camera is
 * translated so `cameraDistance / radius > 0.15`, or WebGL is unavailable,
 * use the flat/tiled parallax renderer instead: cylinder perspective and its
 * seam are no longer stable away from the centre.
 */

export type CylinderPanoramaConfig = {
  radius: number
  verticalFov: number
  horizontalRotation?: number
  aspect: number
}

export type CylinderPanoramaProjection = {
  u: number
  v: number
  direction: [number, number, number]
}

const TAU = Math.PI * 2
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const finiteOr = (value: number, fallback: number) => Number.isFinite(value) ? value : fallback

const normalizedConfig = (config: CylinderPanoramaConfig): Required<CylinderPanoramaConfig> => ({
  radius: Math.max(.001, finiteOr(config.radius, 1)),
  verticalFov: clamp(finiteOr(config.verticalFov, 60), .1, 179),
  horizontalRotation: finiteOr(config.horizontalRotation ?? 0, 0),
  aspect: Math.max(.001, finiteOr(config.aspect, 1)),
})

/** Projects a normalized screen point (`-1..1`, Y up) into panorama UV space. */
export const projectCylinderPanorama = (
  screenX: number,
  screenY: number,
  config: CylinderPanoramaConfig,
): CylinderPanoramaProjection => {
  const safe = normalizedConfig(config)
  const halfFov = safe.verticalFov * Math.PI / 360
  const tangent = Math.tan(halfFov)
  const x = finiteOr(screenX, 0) * safe.aspect * tangent
  const y = finiteOr(screenY, 0) * tangent
  const length = Math.hypot(x, y, 1) || 1
  const ray: [number, number, number] = [x / length, y / length, -1 / length]

  const yaw = safe.horizontalRotation * Math.PI / 180
  const cosYaw = Math.cos(yaw)
  const sinYaw = Math.sin(yaw)
  const rotatedX = ray[0] * cosYaw - ray[2] * sinYaw
  const rotatedZ = ray[0] * sinYaw + ray[2] * cosYaw
  const longitude = Math.atan2(rotatedX, -rotatedZ)
  const latitude = Math.atan2(ray[1], Math.hypot(ray[0], ray[2]))

  return {
    u: ((longitude / TAU) + .5 + 1) % 1,
    v: clamp(.5 - latitude / Math.PI, 0, 1),
    direction: [rotatedX, ray[1], rotatedZ],
  }
}

/** Returns GLSL sources for a fullscreen equirectangular panorama pass. */
export const createCylinderPanoramaShaders = () => ({
  vertex: [
    '#version 300 es',
    'precision highp float;',
    'layout (location = 0) in vec2 aPosition;',
    'out vec2 vScreen;',
    'void main() {',
    '  vScreen = aPosition;',
    '  gl_Position = vec4(aPosition, 0.0, 1.0);',
    '}',
  ].join('\n'),
  fragment: [
    '#version 300 es',
    'precision highp float;',
    'uniform sampler2D uPanorama;',
    'uniform float uHorizontalRotation;',
    'uniform float uVerticalFov;',
    'uniform float uAspect;',
    'in vec2 vScreen;',
    'out vec4 outColor;',
    'const float PI = 3.141592653589793;',
    'const float TAU = 6.283185307179586;',
    'void main() {',
    '  float halfFov = radians(clamp(uVerticalFov, 0.1, 179.0)) * 0.5;',
    '  float tangent = tan(halfFov);',
    '  vec3 ray = normalize(vec3(vScreen.x * uAspect * tangent, vScreen.y * tangent, -1.0));',
    '  float yaw = radians(uHorizontalRotation);',
    '  float c = cos(yaw);',
    '  float s = sin(yaw);',
    '  vec3 rotated = vec3(ray.x * c - ray.z * s, ray.y, ray.x * s + ray.z * c);',
    '  float longitude = atan(rotated.x, -rotated.z);',
    '  float latitude = atan(rotated.y, length(rotated.xz));',
    '  vec2 uv = vec2(fract(longitude / TAU + 0.5 + 1.0), clamp(0.5 - latitude / PI, 0.0, 1.0));',
    '  outColor = texture(uPanorama, uv);',
    '}',
  ].join('\n'),
})

/** True when a translated camera should use flat/tiled parallax instead. */
export const shouldUseParallaxFallback = (cameraDistance: number, radius: number) => {
  const safeRadius = Math.max(.001, finiteOr(radius, 1))
  return Math.abs(finiteOr(cameraDistance, 0)) / safeRadius > .15
}

