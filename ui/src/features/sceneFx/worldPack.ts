import {
  BufferAttribute, BufferGeometry, CircleGeometry, Color, DoubleSide, Group, Mesh,
  PlaneGeometry, Points, ShaderMaterial, SphereGeometry, SRGBColorSpace, Texture, TextureLoader, VideoTexture,
} from 'three'
import { energyMaterial, ENERGY_NOISE, softSparkMaterial } from './energyShaders'
import { fxRandom } from './types'
import type { WorldSfxKind } from './world'

function sheet(kind: Parameters<typeof energyMaterial>[0], color: string, w: number, h = w, billboard = false) {
  return new Mesh(new PlaneGeometry(w, h), energyMaterial(kind, color, billboard))
}

function volumePoints(color: string, mode: string, count: number, spread: number, height: number, size: number) {
  const data = new Float32Array(count * 3)
  for (let i = 0; i < count; i++) {
    data.set([
      (fxRandom(4, i) - 0.5) * spread,
      fxRandom(8, i) * height,
      (fxRandom(12, i) - 0.5) * spread,
    ], i * 3)
  }
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(data, 3))
  geometry.setAttribute('base', new BufferAttribute(data.slice(), 3))
  const points = new Points(geometry, softSparkMaterial(color, size))
  points.userData.kind = mode
  return points
}

function fire(color: string) {
  const root = new Group()
  for (let i = 0; i < 3; i++) {
    const tongue = sheet('fire', color, 0.9 + i * 0.15, 1.7 + i * 0.2, true)
    tongue.userData.seedOffset = i * 11
    tongue.position.set((i - 1) * 0.08, 0.55, (i - 1) * 0.05)
    root.add(tongue)
  }
  root.add(volumePoints('#ffcc77', 'rise', 90, 0.55, 0.2, 0.04))
  return root
}

function weather(kind: 'rain' | 'snow' | 'dust' | 'fog', color: string) {
  const root = new Group()
  if (kind === 'fog') {
    for (let i = 0; i < 6; i++) {
      const cloud = sheet('mist', color, 3.2, 1.5, true)
      cloud.position.set((i - 2.5) * 0.55, 0.3 + (i % 2) * 0.25, (i % 3 - 1) * 0.5)
      cloud.userData.seedOffset = i * 9
      root.add(cloud)
    }
    return root
  }
  const count = kind === 'rain' ? 520 : kind === 'snow' ? 280 : 180
  const size = kind === 'rain' ? 0.09 : kind === 'snow' ? 0.07 : 0.07
  const points = volumePoints(color, kind === 'dust' ? 'drift' : 'fall', count, kind === 'dust' ? 2.6 : 3.4, 3.4, size)
  root.add(points)
  if (kind === 'dust') root.add(sheet('mist', color, 3, 1.2, true))
  return root
}

function shield(color: string) {
  const root = new Group()
  const dome = new Mesh(new SphereGeometry(1, 32, 24), energyMaterial('shield', color))
  dome.userData.kind = 'shield'
  root.add(dome)
  return root
}

function tornado(color: string) {
  const root = new Group()
  for (let i = 0; i < 3; i++) {
    const wall = sheet('tornado', color, 1.3 + i * 0.15, 2.8, true)
    wall.userData.seedOffset = i * 7
    wall.position.y = 1.2
    root.add(wall)
  }
  root.add(volumePoints(color, 'spin', 160, 1.1, 2.4, 0.04))
  return root
}

function splash(color: string) {
  const root = new Group()
  const crown = sheet('splash', color, 2.4, 2.4, true)
  crown.userData.kind = 'flash'
  const ring = sheet('blastRing', color, 3.6)
  ring.rotation.x = -Math.PI / 2
  ring.position.y = 0.02
  root.add(crown, ring, volumePoints(color, 'burst', 140, 0.2, 0.2, 0.05))
  return root
}

function ice(color: string) {
  const root = new Group()
  const burst = sheet('ice', color, 2.6, 2.6, true)
  burst.userData.kind = 'flash'
  const frost = sheet('blastRing', color, 4.2)
  frost.rotation.x = -Math.PI / 2
  frost.position.y = 0.02
  root.add(burst, frost, volumePoints('#d7f6ff', 'burst', 90, 0.18, 0.18, 0.05))
  return root
}

function hole(color: string) {
  const root = new Group()
  const disk = sheet('hole', color, 2.4, 2.4, true)
  disk.userData.kind = 'hole'
  root.add(disk, volumePoints(color, 'spin', 80, 1.3, 0.05, 0.03))
  return root
}

export function portalMediaMaterial(color: string) {
  return new ShaderMaterial({
    name: 'cinematic-portal-media',
    uniforms: {
      uTime: { value: 0 }, uPower: { value: 1 }, uSeed: { value: 1 }, uProgress: { value: 0 },
      uColor: { value: new Color(color) }, uMap: { value: null }, uHasMap: { value: 0 },
    },
    vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`,
    fragmentShader: `varying vec2 vUv; uniform float uTime,uPower,uSeed,uHasMap; uniform vec3 uColor; uniform sampler2D uMap;
      ${ENERGY_NOISE}
      void main() {
        vec2 p=(vUv-.5)*2.; float r=length(p*vec2(1.,1.22)); float a=atan(p.y,p.x);
        float n=fbm(vec2(a*2.2, r*7.-uTime*.8)+uSeed);
        float hole=smoothstep(.97,.7,r);
        vec2 uv=clamp(vUv+(n-.5)*.018,0.,1.);
        vec3 media=uHasMap>0.5 ? texture2D(uMap, uv).rgb : mix(vec3(.02,.05,.1), uColor*.2, n);
        float rim=exp(-abs(r-.78)*34.);
        vec3 color=mix(media, uColor*2.8, rim);
        gl_FragColor=vec4(color*uPower, hole*(.96+rim));
      }`,
    transparent: true, side: DoubleSide, depthWrite: false,
  })
}

function mediaPortal(color: string) {
  const root = new Group()
  const glass = new Mesh(new CircleGeometry(0.78, 64), portalMediaMaterial(color))
  glass.userData.kind = 'portalMedia'
  glass.position.z = -0.03
  const rim = sheet('portal', color, 2.05, 2.55)
  const outer = sheet('circle', color, 2.2)
  outer.position.z = -0.05
  root.add(glass, rim, outer)
  return root
}

export function buildPackedEffect(kind: WorldSfxKind, color: string): Group | null {
  switch (kind) {
    case 'fire': return fire(color)
    case 'rain': return weather('rain', color)
    case 'snow': return weather('snow', color)
    case 'fog': return weather('fog', color)
    case 'dust': return weather('dust', color)
    case 'shield': return shield(color)
    case 'tornado': return tornado(color)
    case 'splash': return splash(color)
    case 'ice_burst': return ice(color)
    case 'black_hole': return hole(color)
    case 'media_portal': return mediaPortal(color)
    default: return null
  }
}

const textures = new Map<string, Texture>()

export function applyPortalMedia(root: Group, url?: string) {
  const mesh = root.children.find(child => child.userData.kind === 'portalMedia')
  if (!(mesh instanceof Mesh) || !(mesh.material instanceof ShaderMaterial)) return
  const uniforms = mesh.material.uniforms
  if (typeof document === 'undefined') return
  if (!url) {
    uniforms.uMap.value = null
    uniforms.uHasMap.value = 0
    return
  }
  const cached = textures.get(url)
  if (cached) {
    uniforms.uMap.value = cached
    uniforms.uHasMap.value = 1
    return
  }
  if (/\.(mp4|webm|mov|mkv)(\?|$)/i.test(url) || url.startsWith('blob:')) {
    const video = document.createElement('video')
    video.src = url
    video.crossOrigin = 'anonymous'
    video.loop = true
    video.muted = true
    video.playsInline = true
    video.autoplay = true
    const bind = () => {
      const texture = new VideoTexture(video)
      texture.colorSpace = SRGBColorSpace
      textures.set(url, texture)
      uniforms.uMap.value = texture
      uniforms.uHasMap.value = 1
      void video.play().catch(() => undefined)
    }
    video.addEventListener('loadeddata', bind, { once: true })
    if (!/\.(mp4|webm|mov|mkv)(\?|$)/i.test(url)) {
      new TextureLoader().load(url, texture => {
        texture.colorSpace = SRGBColorSpace
        textures.set(url, texture)
        uniforms.uMap.value = texture
        uniforms.uHasMap.value = 1
      }, undefined, () => undefined)
    }
    return
  }
  new TextureLoader().load(url, texture => {
    texture.colorSpace = SRGBColorSpace
    textures.set(url, texture)
    uniforms.uMap.value = texture
    uniforms.uHasMap.value = 1
  }, undefined, () => undefined)
}
