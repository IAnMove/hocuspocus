import { AdditiveBlending, BufferAttribute, BufferGeometry, Color, Group, Mesh, ShaderMaterial, Vector3 } from 'three'
import { boltChannels, strikeState, type BoltChannel } from './lightningBolt'
import type { WorldSfx } from './world'

const MAX_SEGMENTS = 512
const scratchAxis = new Vector3(), scratchU = new Vector3(), scratchV = new Vector3()

/** Each segment is a quad that the vertex shader turns to face the camera,
 *  with a white core and coloured halo across its width. */
function boltMaterial(color: string) {
  return new ShaderMaterial({
    name: 'cinematic-lightning',
    uniforms: { uColor: { value: new Color(color) }, uBright: { value: 0 }, uWidth: { value: .05 }, uLeader: { value: 1 } },
    vertexShader: `attribute vec3 aStart, aEnd; attribute float aSide, aAlong, aWidth, aOrder;
      uniform float uWidth, uLeader; varying float vSide, vLit, vWeight;
      void main() {
        vec4 a=modelViewMatrix*vec4(aStart,1.), b=modelViewMatrix*vec4(aEnd,1.);
        vec3 p=mix(a.xyz,b.xyz,aAlong), dir=normalize(b.xyz-a.xyz+vec3(1e-6));
        vec3 side=normalize(cross(dir, normalize(-p)+vec3(0.,0.,1e-6)));
        float w=uWidth*aWidth;
        p+=side*aSide*w+dir*(aAlong*2.-1.)*w*.35;
        vSide=aSide; vWeight=aWidth; vLit=step(aOrder,uLeader);
        gl_Position=projectionMatrix*vec4(p,1.);
      }`,
    fragmentShader: `uniform vec3 uColor; uniform float uBright; varying float vSide, vLit, vWeight;
      void main() {
        float d=abs(vSide), core=exp(-d*d*70.), halo=exp(-d*d*6.)*.5;
        vec3 color=mix(uColor, vec3(1.), core*.85)*(core*3.2+halo*1.4);
        float power=uBright*vLit*(.55+vWeight*.45);
        gl_FragColor=vec4(color*power, clamp((core+halo)*power,0.,1.));
      }`,
    transparent: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false,
  })
}

export function buildLightning(color: string) {
  const root = new Group()
  const geometry = new BufferGeometry()
  const vertices = MAX_SEGMENTS * 4
  for (const [name, size] of [['aStart', 3], ['aEnd', 3], ['aSide', 1], ['aAlong', 1], ['aWidth', 1], ['aOrder', 1]] as const) {
    geometry.setAttribute(name, new BufferAttribute(new Float32Array(vertices * size), size))
  }
  // three needs a position attribute for bounds; the shader never reads it.
  geometry.setAttribute('position', new BufferAttribute(new Float32Array(vertices * 3), 3))
  const index = new Uint16Array(MAX_SEGMENTS * 6)
  for (let i = 0; i < MAX_SEGMENTS; i++) index.set([i * 4, i * 4 + 1, i * 4 + 2, i * 4 + 2, i * 4 + 1, i * 4 + 3], i * 6)
  geometry.setIndex(new BufferAttribute(index, 1))
  geometry.setDrawRange(0, 0)
  const bolt = new Mesh(geometry, boltMaterial(color))
  bolt.userData.kind = 'bolt'
  bolt.frustumCulled = false
  root.add(bolt)
  return root
}

function basis(from: Vector3, to: Vector3) {
  const axis = scratchAxis.copy(to).sub(from)
  const length = Math.max(.05, axis.length())
  axis.multiplyScalar(1 / length)
  const helper = Math.abs(axis.y) > .9 ? new Vector3(1, 0, 0) : new Vector3(0, 1, 0)
  const u = scratchU.crossVectors(axis, helper).normalize()
  const v = scratchV.crossVectors(axis, u).normalize()
  return { axis, u, v, length }
}

function writeChannels(geometry: BufferGeometry, channels: BoltChannel[], from: Vector3, to: Vector3) {
  const { axis, u, v, length } = basis(from, to)
  const start = geometry.getAttribute('aStart') as BufferAttribute, end = geometry.getAttribute('aEnd') as BufferAttribute
  const side = geometry.getAttribute('aSide') as BufferAttribute, along = geometry.getAttribute('aAlong') as BufferAttribute
  const width = geometry.getAttribute('aWidth') as BufferAttribute, order = geometry.getAttribute('aOrder') as BufferAttribute
  const world = ([x, y, z]: [number, number, number]) => [
    from.x + (axis.x * y + u.x * x + v.x * z) * length,
    from.y + (axis.y * y + u.y * x + v.y * z) * length,
    from.z + (axis.z * y + u.z * x + v.z * z) * length,
  ]
  let segment = 0
  for (const channel of channels) {
    for (let i = 1; i < channel.points.length && segment < MAX_SEGMENTS; i++, segment++) {
      const a = world(channel.points[i - 1]), b = world(channel.points[i])
      for (let corner = 0; corner < 4; corner++) {
        const at = segment * 4 + corner
        start.setXYZ(at, a[0], a[1], a[2]); end.setXYZ(at, b[0], b[1], b[2])
        side.setX(at, corner % 2 ? 1 : -1); along.setX(at, corner < 2 ? 0 : 1)
        width.setX(at, channel.width); order.setX(at, channel.order[i - 1])
      }
    }
  }
  for (const attribute of [start, end, side, along, width, order]) attribute.needsUpdate = true
  geometry.setDrawRange(0, segment * 6)
}

/** Pose the bolt between two world points for the strike live at `seconds`. */
export function poseLightning(root: Group, cue: WorldSfx, from: Vector3, to: Vector3, seconds: number) {
  const bolt = root.children.find(child => child.userData.kind === 'bolt')
  if (!(bolt instanceof Mesh)) return
  root.position.set(0, 0, 0); root.rotation.set(0, 0, 0); root.scale.setScalar(1)
  const local = Math.max(0, seconds - cue.start)
  const state = strikeState(cue.seed, local, Math.max(.001, cue.end - cue.start))
  writeChannels(bolt.geometry, boltChannels(cue.seed * 31 + state.strike), from, to)
  const uniforms = (bolt.material as ShaderMaterial).uniforms
  uniforms.uBright.value = state.brightness * cue.intensity
  uniforms.uLeader.value = state.leader
  uniforms.uWidth.value = .085 * cue.scale
  root.userData.strikeAt = to.clone()
}

/** Scene light a lightning cue throws at `seconds`, 0 between strikes. */
export function lightningGlow(cue: Pick<WorldSfx, 'seed' | 'start' | 'end' | 'intensity'>, seconds: number) {
  return strikeState(cue.seed, Math.max(0, seconds - cue.start), Math.max(.001, cue.end - cue.start)).brightness * cue.intensity
}
