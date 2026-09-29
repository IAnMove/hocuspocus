import { Color, Matrix4, Vector2, Vector3, type Camera, type DirectionalLight, type WebGLRenderer, type WebGLRenderTarget } from 'three'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'

const FULLSCREEN = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const SHAFT = {
  name: 'AtmosShafts',
  uniforms: {
    tDiffuse: { value: null },
    tDepth: { value: null },
    tShadow: { value: null },
    uSunUv: { value: new Vector2(0.3, 0.72) },
    uStrength: { value: 0.45 },
    uSteps: { value: 12 },
    uMarch: { value: 0 },
    uRay: { value: new Vector3(0, -1, 0) },
    uShadowMatrix: { value: new Matrix4() },
    uFogColor: { value: new Color('#d5e6c6') },
    uFogDensity: { value: 0.08 },
    uFogHeight: { value: 4.5 },
    uProjectionInverse: { value: new Matrix4() },
    uViewInverse: { value: new Matrix4() },
    uNear: { value: 0.05 },
    uFar: { value: 80 },
  },
  vertexShader: FULLSCREEN,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform sampler2D tDepth;
    uniform sampler2D tShadow;
    uniform vec2 uSunUv;
    uniform float uStrength;
    uniform float uSteps;
    uniform float uMarch;
    uniform vec3 uRay;
    uniform mat4 uShadowMatrix;
    uniform vec3 uFogColor;
    uniform float uFogDensity;
    uniform float uFogHeight;
    uniform mat4 uProjectionInverse;
    uniform mat4 uViewInverse;
    uniform float uNear;
    uniform float uFar;
    varying vec2 vUv;
    #include <packing>
    float phase(float cosTheta) {
      const float g = 0.6;
      float d = 1.0 + g * g - 2.0 * g * cosTheta;
      return (1.0 - g * g) / max(0.08, pow(d, 1.5));
    }
    float marchLit(vec3 world, vec3 towardSun) {
      float acc = 0.0;
      float steps = min(uSteps, 32.0);
      float jitter = fract(sin(dot(vUv, vec2(127.1, 311.7))) * 43758.5453);
      for (int i = 0; i < 32; i++) {
        if (float(i) >= steps) break;
        vec3 p = world + towardSun * (0.35 + (float(i) + jitter) * 0.45);
        float fog = exp(-max(p.y, 0.0) / uFogHeight) * uFogDensity;
        vec4 sc = uShadowMatrix * vec4(p, 1.0);
        sc.xyz /= sc.w;
        float lit = 0.0;
        if (sc.x > 0.0 && sc.x < 1.0 && sc.y > 0.0 && sc.y < 1.0) {
          float blocker = texture2D(tShadow, sc.xy).r;
          lit = step(sc.z, blocker + 0.0025);
        }
        float cosTheta = dot(normalize(p), -uRay);
        acc += lit * fog * phase(clamp(cosTheta, -1.0, 1.0));
      }
      return acc / max(1.0, steps);
    }
    void main() {
      vec3 base = texture2D(tDiffuse, vUv).rgb;
      vec2 delta = vUv - uSunUv;
      vec3 shafts = vec3(0.0);
      float steps = clamp(uSteps, 4.0, 16.0);
      for (int i = 0; i < 16; i++) {
        if (float(i) >= steps) break;
        vec2 p = vUv - delta * (float(i) / steps) * 0.72;
        vec3 s = texture2D(tDiffuse, p).rgb;
        float lum = dot(s, vec3(0.299, 0.587, 0.114));
        shafts += s * smoothstep(0.82, 0.98, lum);
      }
      shafts /= steps;
      float march = 0.0;
      if (uMarch > 0.5) {
        float depth = texture2D(tDepth, vUv).x;
        vec4 clip = vec4(vUv * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
        vec4 view = uProjectionInverse * clip;
        view.xyz /= view.w;
        vec4 world = uViewInverse * vec4(view.xyz, 1.0);
        march = marchLit(world.xyz, -normalize(uRay));
      }
      vec3 color = base + min(shafts * uStrength, vec3(0.28)) + uFogColor * march * 0.9;
      gl_FragColor = vec4(color, 1.0);
    }
  `,
}

const GRADE = {
  name: 'AtmosGrade',
  uniforms: {
    tDiffuse: { value: null },
    uTemperature: { value: 0.18 },
    uTint: { value: 0.04 },
    uContrast: { value: 1.08 },
    uFrame: { value: 0 },
    uVignette: { value: 0.28 },
  },
  vertexShader: FULLSCREEN,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform float uTemperature;
    uniform float uTint;
    uniform float uContrast;
    uniform float uFrame;
    uniform float uVignette;
    varying vec2 vUv;
    void main() {
      vec3 color = texture2D(tDiffuse, vUv).rgb;
      color.r += uTemperature * 0.08;
      color.b -= uTemperature * 0.06;
      color.g += uTint * 0.05;
      color = (color - 0.5) * uContrast + 0.5;
      float grain = fract(sin(dot(vUv * (uFrame + 1.0), vec2(12.9898, 78.233))) * 43758.5453);
      color += (grain - 0.5) * 0.018;
      float vig = smoothstep(0.95, 0.25, length(vUv - 0.5));
      color *= mix(1.0 - uVignette, 1.0, vig);
      gl_FragColor = vec4(color, 1.0);
    }
  `,
}

const DOF = {
  name: 'AtmosDof',
  uniforms: {
    tDiffuse: { value: null },
    tDepth: { value: null },
    uFocus: { value: 3.4 },
    uNear: { value: 0.05 },
    uFar: { value: 80 },
  },
  vertexShader: FULLSCREEN,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform sampler2D tDepth;
    uniform float uFocus;
    uniform float uNear;
    uniform float uFar;
    varying vec2 vUv;
    #include <packing>
    void main() {
      float depth = texture2D(tDepth, vUv).x;
      vec3 sharp = texture2D(tDiffuse, vUv).rgb;
      if (depth <= 0.0001) {
        gl_FragColor = vec4(sharp, 1.0);
        return;
      }
      float viewZ = perspectiveDepthToViewZ(depth, uNear, uFar);
      float dist = -viewZ;
      float coc = smoothstep(1.15, 0.3, dist);
      vec3 acc = vec3(0.0);
      float w = 0.0;
      for (int i = 0; i < 8; i++) {
        float a = float(i) * 0.785398;
        vec2 off = vec2(cos(a), sin(a)) * coc * 0.018;
        acc += texture2D(tDiffuse, vUv + off).rgb;
        w += 1.0;
      }
      gl_FragColor = vec4(acc / w, 1.0);
    }
  `,
}

export type ShaftUniforms = typeof SHAFT.uniforms

export function createShaftPass(): ShaderPass {
  return new DepthBinder(SHAFT)
}

export function createGradePass(): ShaderPass {
  return new ShaderPass(GRADE)
}

export function createDofPass(): ShaderPass {
  const pass = new DepthBinder(DOF)
  pass.depthFrom = 'write'
  return pass
}

export function projectSun(camera: Camera, ray: Vector3, target: Vector2) {
  const sun = camera.position.clone().addScaledVector(ray, -40)
  sun.project(camera)
  target.set((sun.x + 1) / 2, (sun.y + 1) / 2)
}

export function bindShaftLight(pass: ShaderPass, light: DirectionalLight, march: boolean) {
  const uniforms = pass.uniforms
  uniforms.uRay.value.copy(light.position).multiplyScalar(-1).normalize()
  uniforms.uMarch.value = march && light.shadow.map ? 1 : 0
  if (light.shadow.map) {
    uniforms.tShadow.value = light.shadow.map.texture
    uniforms.uShadowMatrix.value.copy(light.shadow.matrix)
  }
}

export class DepthBinder extends ShaderPass {
  depthFrom: 'read' | 'write' = 'read'
  constructor(shader: object) {
    super(shader as never)
  }
  override render(renderer: WebGLRenderer, writeBuffer: WebGLRenderTarget, readBuffer: WebGLRenderTarget) {
    const source = this.depthFrom === 'write' ? writeBuffer : readBuffer
    if (this.uniforms?.tDepth) this.uniforms.tDepth.value = source.depthTexture
    super.render(renderer, writeBuffer, readBuffer, 0, false)
  }
}
