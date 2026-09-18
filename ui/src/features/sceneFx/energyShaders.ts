import { AdditiveBlending, Color, DoubleSide, ShaderMaterial } from 'three'

export const ENERGY_NOISE = `
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
float noise2(vec2 p) {
  vec2 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),
             mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);
}
float fbm(vec2 p) {
  float s=0., a=.5;
  for(int i=0;i<5;i++) { s+=a*noise2(p); p=p*2.07+vec2(17.2,31.7); a*=.5; }
  return s;
}`

const VERTEX = `varying vec2 vUv;
void main() { vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`
const BILLBOARD = `varying vec2 vUv;
void main() {
  vUv=uv;
  vec4 center=modelViewMatrix*vec4(0.,0.,0.,1.);
  center.xy+=position.xy*vec2(length(modelMatrix[0].xyz),length(modelMatrix[1].xyz));
  gl_Position=projectionMatrix*center;
}`

export type EnergySurface = 'portal' | 'circle' | 'beam' | 'orb' | 'aura' | 'shock' | 'mist' | 'fireball' | 'flash' | 'blastRing' | 'fire' | 'shield' | 'tornado' | 'splash' | 'ice' | 'hole' | 'portalGlass'
const BODIES: Record<EnergySurface, string> = {
  portal: `
    vec2 p=(vUv-.5)*2.; float r=length(p), a=atan(p.y,p.x);
    float n=fbm(vec2(a*3.,r*10.-uTime*2.+uSeed));
    float rim=exp(-abs(r-.69-(n-.5)*.10)*48.);
    float halo=exp(-abs(r-.69)*11.)*.18;
    float strands=pow(fbm(vec2(a*9.+uTime,r*15.-uTime*4.)),3.)
      *smoothstep(.35,.65,r)*(1.-smoothstep(.7,.95,r));
    float alpha=rim+halo+strands;
    vec3 color=mix(uColor*.65,vec3(.75,.95,1.),rim*.65);
    gl_FragColor=vec4(color*(rim*4.+halo+strands*2.)*uPower,alpha*uPower);`,
  circle: `
    vec2 p=(vUv-.5)*2.; float r=length(p),a=atan(p.y,p.x);
    float rings=exp(-abs(r-.72)*150.)+exp(-abs(r-.48)*170.)*.55;
    float marks=pow(abs(sin(a*16.+uTime*.25)),22.)
      *smoothstep(.52,.55,r)*(1.-smoothstep(.63,.65,r));
    float flare=exp(-abs(r-.72)*22.)*.16;
    gl_FragColor=vec4(uColor*(rings*3.+marks*1.7+flare)*uPower,
      (rings+marks+flare)*uPower);`,
  beam: `
    float core=pow(max(0.,1.-abs(vUv.x-.5)*2.),4.);
    float flow=.55+fbm(vec2(vUv.x*6.,vUv.y*16.-uTime*5.+uSeed));
    float ends=smoothstep(0.,.04,vUv.y)*(1.-smoothstep(.96,1.,vUv.y));
    gl_FragColor=vec4(mix(uColor,vec3(1.),core*.5)*core*flow*4.*uPower,core*ends*uPower);`,
  orb: `
    float r=length((vUv-.5)*2.);
    float core=exp(-r*r*35.), halo=exp(-r*r*5.);
    float filaments=pow(fbm(vUv*9.+vec2(uTime,-uTime)*.5),3.)*(1.-smoothstep(.4,.85,r));
    gl_FragColor=vec4((uColor*(halo*.9+filaments*3.)+vec3(core)*3.)*uPower,(halo+core)*uPower);`,
  aura: `
    vec2 p=vUv; float edge=pow(max(0.,1.-abs(p.x-.5)*2.),1.5);
    float n=fbm(vec2(p.x*8.,p.y*5.-uTime*1.7+uSeed));
    float flame=smoothstep(.28,.72,n)*edge*(1.-smoothstep(.35,.95,p.y));
    float shell=pow(max(0.,1.-abs(length((p-vec2(.5,.38))*vec2(2.,1.3))-.5)*12.),2.);
    gl_FragColor=vec4(uColor*(flame*2.+shell*.25)*uPower,(flame*.7+shell*.12)*uPower);`,
  shock: `
    float r=length((vUv-.5)*2.), radius=.08+uProgress*.82;
    float band=exp(-abs(r-radius)*90.), dust=exp(-abs(r-radius)*16.)
      *fbm(vUv*13.+uTime)*.35;
    float fade=1.-uProgress;
    gl_FragColor=vec4(uColor*(band*3.+dust)*uPower,(band+dust)*fade*uPower);`,
  mist: `
    vec2 p=vUv-.5; float edge=1.-smoothstep(.12,.52,length(p));
    float n=fbm(vUv*5.+vec2(uTime*.12+uSeed,uTime*-.075));
    float alpha=smoothstep(.28,.74,n)*edge*.55;
    float light=fbm(vUv*7.+n+uTime*.04);
    gl_FragColor=vec4(uColor*(.3+light*.65),alpha*uPower);`,
  fireball: `
    vec2 p=(vUv-.5)*vec2(2.,2.15); float r=length(p), a=atan(p.y,p.x);
    float n=fbm(vec2(a*2.4, r*5.2-uTime*2.4)+uSeed);
    float n2=fbm(vec2(a*5.1+uTime, r*7.-uTime*3.1));
    float edge=r-(n-.5)*.55-(n2-.5)*.22;
    float body=smoothstep(.92,.12,edge);
    float tongues=pow(max(n2,0.),2.1)*smoothstep(.95,.2,r);
    float core=exp(-edge*edge*9.)*smoothstep(.9,.05,r);
    float fade=pow(max(0.,1.-uProgress*.82),1.08);
    float card=1.-smoothstep(.42,.5,max(abs(vUv.x-.5),abs(vUv.y-.5)));
    float alpha=(body*.7+tongues*.55+core*.85)*fade*card;
    vec3 coal=uColor*.35;
    vec3 flame=mix(uColor,vec3(1.,.45,.05),tongues);
    vec3 hot=mix(flame,vec3(1.,.82,.42),core*.7);
    gl_FragColor=vec4(mix(coal,hot,body)*(1.8+core*4.)*uPower,alpha*uPower);`,
  flash: `
    vec2 p=(vUv-.5)*2.; float r=length(p);
    float n=fbm(vUv*9.+uSeed);
    float core=exp(-r*r*(9.+n*4.));
    float halo=exp(-r*r*(1.6+n))*step(.22,n);
    float fade=pow(max(0.,1.-uProgress*3.1),1.8);
    float card=1.-smoothstep(.4,.5,max(abs(vUv.x-.5),abs(vUv.y-.5)));
    gl_FragColor=vec4((vec3(1.,.9,.55)*core*7.+uColor*halo*2.2)*uPower*fade,(core*.8+halo*.3)*fade*uPower*card);`,
  blastRing: `
    vec2 p=(vUv-.5)*2.; float r=length(p), a=atan(p.y,p.x);
    float radius=.12+uProgress*.78;
    float n=fbm(vec2(a*3.5, r*10.)+uSeed);
    float band=exp(-abs(r-radius-(n-.5)*.11)*28.);
    float grit=pow(n,2.)*exp(-abs(r-radius)*8.);
    float fade=(1.-uProgress)*step(.18,n+.35);
    gl_FragColor=vec4(uColor*(band*2.6+grit*1.4)*uPower,(band*.7+grit)*fade*uPower);`,
  fire: `
    vec2 p=vUv; float n=fbm(vec2(p.x*9., p.y*6.-uTime*2.4)+uSeed);
    float n2=fbm(vec2(p.x*14.+uTime, p.y*8.-uTime*3.1));
    float edge=pow(max(0.,1.-abs(p.x-.5)*2.15),1.35);
    float flame=smoothstep(.18,.78,n)*edge*(1.-smoothstep(.12,.98,p.y));
    float tongues=pow(n2,2.2)*edge*smoothstep(.95,.25,p.y);
    float core=exp(-pow((p.x-.5)*6.,2.))*smoothstep(.9,.2,p.y);
    vec3 hot=mix(uColor,vec3(1.,.55,.08),tongues);
    hot=mix(hot,vec3(1.,.9,.45),core*.7);
    float card=1.-smoothstep(.46,.5,abs(p.x-.5));
    gl_FragColor=vec4(hot*(flame*2.4+tongues*3.+core*4.)*uPower,(flame*.75+tongues*.5+core)*card*uPower);`,
  shield: `
    vec2 p=(vUv-.5)*2.; float r=length(p);
    float n=fbm(p*4.+uTime*.3+uSeed);
    float fres=pow(max(0.,1.-r),1.4);
    float hex=pow(abs(sin(p.x*18.)*sin(p.y*16.)),12.)*smoothstep(1.,.35,r);
    float rim=exp(-abs(r-.86)*28.);
    float alpha=(fres*.18+rim*.85+hex*.25)*uPower;
    gl_FragColor=vec4(mix(uColor,vec3(.7,.95,1.),rim)*(1.4+hex*2.)*uPower,alpha);`,
  tornado: `
    vec2 p=vUv-.5; float x=p.x*2., y=p.y+.5;
    float spin=fbm(vec2(x*6.+uTime*2.2, y*4.));
    float funnel=pow(max(0.,1.-abs(x)/(0.18+y*.7)),1.4);
    float dust=pow(spin,1.6)*funnel;
    float card=smoothstep(.5,.38,abs(p.x));
    gl_FragColor=vec4(uColor*(funnel*.7+dust*1.8)*uPower,(funnel*.28+dust*.55)*card*uPower);`,
  splash: `
    vec2 p=(vUv-.5)*2.; float r=length(p), a=atan(p.y,p.x);
    float n=fbm(vec2(a*4., r*6.-uTime)+uSeed);
    float crown=smoothstep(.15,.02,abs(r-.35-(n-.5)*.18))*step(p.y,-.05+n*.2);
    float drops=exp(-r*r*3.)*pow(n,3.);
    float fade=pow(max(0.,1.-uProgress),1.1);
    gl_FragColor=vec4(mix(uColor,vec3(.85,.95,1.),drops)*(crown*3.+drops*2.)*uPower,(crown*.7+drops)*fade*uPower);`,
  ice: `
    vec2 p=(vUv-.5)*2.; float r=length(p), a=atan(p.y,p.x);
    float n=fbm(p*7.+uSeed);
    float shard=pow(abs(sin(a*5.+n*2.)), 6.)*smoothstep(1.,.15,r);
    float frost=n*smoothstep(.95,.2,r);
    float core=exp(-r*r*8.);
    float fade=pow(max(0.,1.-uProgress*.7),1.05);
    gl_FragColor=vec4(mix(uColor,vec3(.85,.95,1.),shard)*(shard*3.+frost+core*2.)*uPower,(shard*.8+frost*.35+core)*fade*uPower);`,
  hole: `
    vec2 p=(vUv-.5)*2.; float r=length(p), a=atan(p.y,p.x);
    float n=fbm(vec2(a*3., r*8.-uTime*.8));
    float disk=smoothstep(.55,.22,r)*smoothstep(.02,.18,r);
    float event=smoothstep(.2,.0,r);
    float arc=exp(-abs(r-.38-(n-.5)*.06)*22.);
    gl_FragColor=vec4(mix(vec3(0.), uColor, arc+disk*.25)*(arc*4.+disk)*uPower,(disk*.55+arc+event)*uPower);`,
  portalGlass: `
    vec2 p=(vUv-.5)*2.; float r=length(p*vec2(1.,1.22));
    float n=fbm(vUv*7.+uTime*.35+uSeed);
    float hole=smoothstep(.96,.68,r);
    vec3 voidc=mix(vec3(.01,.03,.07), uColor*.12, n);
    gl_FragColor=vec4(voidc, hole*.92);`,
}

export function energyMaterial(kind: EnergySurface, color: string, billboard = false) {
  return new ShaderMaterial({
    name: `cinematic-${kind}`,
    uniforms: { uTime: { value: 0 }, uPower: { value: 1 }, uSeed: { value: 1 },
      uProgress: { value: 0 }, uColor: { value: new Color(color) } },
    vertexShader: billboard ? BILLBOARD : VERTEX,
    fragmentShader: `varying vec2 vUv; uniform float uTime,uPower,uSeed,uProgress;
      uniform vec3 uColor; ${ENERGY_NOISE} void main() { ${BODIES[kind]} }`,
    transparent: true, depthWrite: false, side: DoubleSide,
    ...(kind === 'mist' || kind === 'portalGlass' || kind === 'hole' ? {} : { blending: AdditiveBlending }),
  })
}

export function softSparkMaterial(color: string, size = .045) {
  return new ShaderMaterial({
    name: 'cinematic-sparks',
    uniforms: { uColor: { value: new Color(color) }, uSize: { value: size }, uPower: { value: 1 } },
    vertexShader: `uniform float uSize;
      void main() { vec4 p=modelViewMatrix*vec4(position,1.);
      gl_PointSize=clamp(uSize*700./max(.1,-p.z),1.,24.);
      gl_Position=projectionMatrix*p; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uPower;
      void main() { float a=pow(max(0.,1.-length(gl_PointCoord-.5)*2.),2.);
      gl_FragColor=vec4(uColor*3.*uPower,a*uPower); }`,
    transparent: true, depthWrite: false, blending: AdditiveBlending,
  })
}
