import { DoubleSide, Mesh, PlaneGeometry, ShaderMaterial, type Scene } from 'three'

export type EndlessRoadSettings = { speed: number; slope: number; offset: number }
const bounded = (v: unknown, fallback: number, min: number, max: number) => typeof v === 'number' && Number.isFinite(v) ? Math.max(min, Math.min(max, v)) : fallback
export function parseEndlessRoad(raw: unknown): EndlessRoadSettings | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const v = raw as EndlessRoadSettings
  return { speed: bounded(v.speed, 3, -30, 30), slope: bounded(v.slope, 0, -35, 35), offset: bounded(v.offset, 0, -36000, 36000) }
}

/** Absolute timeline phase lets separate shots share one uninterrupted road. */
export function roadPhase(settings: EndlessRoadSettings, seconds: number) {
  return (settings.offset + seconds) * settings.speed
}

export class EndlessRoad {
  readonly mesh: Mesh<PlaneGeometry, ShaderMaterial>
  constructor(scene: Scene) {
    const material = new ShaderMaterial({ side: DoubleSide, uniforms: { phase: { value: 0 } },
      vertexShader: `varying vec2 road;
        void main(){road=position.xy;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
      fragmentShader: `varying vec2 road; uniform float phase;
        float noise(vec2 p){return fract(sin(dot(floor(p),vec2(127.1,311.7)))*43758.5453);}
        void main(){vec2 p=vec2(road.x-phase,road.y);float z=abs(p.y);
          float grain=noise(p*65.);vec3 asphalt=vec3(.018,.024,.032)+grain*.012;
          vec3 shoulder=vec3(.026,.032,.042)+noise(p*9.)*.012;
          vec3 col=mix(asphalt,shoulder,smoothstep(2.5,2.55,z));
          float edge=1.-smoothstep(.035,.06,abs(z-2.3));
          float dash=(1.-smoothstep(.028,.05,abs(p.y+.7)))*(1.-smoothstep(1.35,1.4,mod(p.x,2.5)));
          col=mix(col,vec3(.67,.52,.19),dash*.9);col=mix(col,vec3(.48,.55,.62),edge);
          float curb=(1.-smoothstep(.08,.12,abs(z-2.65)));
          col=mix(col,mix(vec3(.13,.16,.19),vec3(.035),step(.5,fract(p.x*.7))),curb);
          gl_FragColor=vec4(col,1.);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }` })
    this.mesh = new Mesh(new PlaneGeometry(200, 80), material)
    this.mesh.rotation.order = 'ZYX'
    this.mesh.rotation.x = -Math.PI / 2
    scene.add(this.mesh)
  }
  sync(active: boolean, settings: EndlessRoadSettings | undefined, seconds: number) {
    this.mesh.visible = active
    const value = settings ?? { speed: 3, slope: 0, offset: 0 }
    this.mesh.rotation.z = value.slope * Math.PI / 180
    this.mesh.material.uniforms.phase.value = roadPhase(value, seconds)
  }
  dispose() { this.mesh.removeFromParent(); this.mesh.geometry.dispose(); this.mesh.material.dispose() }
}
