import * as THREE from 'three';

export const EXPRESSIONS = {
  neutral: { label: 'Neutral', values: [0, 0, 0, 0], brows: 0 },
  happy: { label: 'Happy', values: [.06, .28, 0, .10], brows: 0 },
  angry: { label: 'Angry', values: [.30, .08, .65, -.15], brows: 1 },
  worried: { label: 'Worried', values: [.10, .08, -.55, .15], brows: 1 },
  surprised: { label: 'Surprised', values: [0, 0, 0, .65], brows: 1 },
  sleepy: { label: 'Sleepy', values: [.70, .06, 0, -.15], brows: 0 },
};
export const EYE_PROFILES = {
  human_mira: { rise: .33, spacing: .19, width: .225, height: .12 },
  elf_seren: { rise: .24, spacing: .19, width: .205, height: .115 },
  orc_grog: { rise: .245, spacing: .22, width: .20, height: .115 },
  goblin_zik: { rise: .23, spacing: .20, width: .21, height: .13 },
};
export function blinkAt(time: number) {
  const phase = (time + 1.9) % 4.7;
  if (phase > .24) return 0;
  return Math.sin(Math.PI * phase / .24) ** 2;
}
export function eyeUniforms() {
  return {
    eyeLeft: { value: new THREE.Vector3(-.04, 1.53, .10) }, eyeRight: { value: new THREE.Vector3(.04, 1.53, .10) },
    eyeSize: { value: new THREE.Vector2(.045, .024) },
    eyeSkinLeft: { value: new THREE.Color('#d9b69b') }, eyeSkinRight: { value: new THREE.Color('#d9b69b') },
    eyeExpression: { value: new THREE.Vector4() }, eyeBlink: { value: 0 }, eyeBrows: { value: 0 }, eyesEnabled: { value: 0 },
  };
}
// Engine-independent GLSL, shared verbatim with the generated Godot shader.
export const EYE_FUNCTION = `
vec4 eyeLayer(vec3 point, vec3 center, vec2 size, vec3 skin, float side, vec4 expression, float blink, float brows) {
  vec2 q = (point.xy-center.xy)/size;
  float front = smoothstep(center.z-0.045, center.z-0.015, point.z);
  float oval = 1.0-smoothstep(0.86,1.10,length(q*vec2(1.64,1.36)));
  float top = 0.35-expression.x*0.65-blink*1.0 + q.x*q.x*0.10;
  float bottom = -0.36+expression.y*0.60;
  float upper = smoothstep(top-0.025,top+0.025,q.y)*min(1.0,(expression.x+blink)*8.0);
  float lower = (1.0-smoothstep(bottom-0.025,bottom+0.025,q.y))*min(1.0,expression.y*8.0);
  float alpha = max(upper,lower)*oval;
  vec3 color = skin;
  float creaseY = mix(top, -0.03 + q.x*q.x*0.5, smoothstep(0.65,0.95,blink));
  float crease = (1.0-smoothstep(0.014,0.055,abs(q.y-creaseY)))*(1.0-smoothstep(0.40,0.52,abs(q.x)));
  crease *= min(1.0,blink*2.0+expression.x+expression.y)*oval;
  color = mix(color,skin*0.24,crease);
  alpha = max(alpha,crease);
  float browArea = (1.0-smoothstep(.55,.76,abs(q.x)))*smoothstep(.5,.68,q.y)*(1.0-smoothstep(1.75,1.95,q.y))*brows;
  float browY = 1.02 + expression.w*.5 + expression.z*side*q.x;
  float brow = (1.0-smoothstep(.05,.13,abs(q.y-browY)))*(1.0-smoothstep(.50,.65,abs(q.x)))*brows;
  color = mix(color,skin,browArea);
  color = mix(color,skin*0.13,brow);
  alpha = max(alpha,max(browArea,brow));
  return vec4(color,alpha*front);
}
`;
export const EYE_DECLARATIONS = `
uniform vec3 eyeLeft; uniform vec3 eyeRight; uniform vec2 eyeSize;
uniform vec3 eyeSkinLeft; uniform vec3 eyeSkinRight; uniform vec4 eyeExpression;
uniform float eyeBlink; uniform float eyeBrows; uniform float eyesEnabled;
${EYE_FUNCTION}
`;
