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

export type EnergySurface = 'portal' | 'circle' | 'beam' | 'orb' | 'aura' | 'shock' | 'mist' | 'fireball' | 'flash' | 'blastRing' | 'fire' | 'tornado' | 'splash' | 'ice' | 'hole' | 'portalGlass'
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
    vec2 p=vUv-.5; float edge=1.-smoothstep(.12,.48,length(p));
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
    vec2 p=vUv; float y=p.y, x=p.x-.5;
    float n1=fbm(vec2(x*3.5+uSeed, y*2.2-uTime*1.9));
    float n2=fbm(vec2(x*7.+uSeed*2., y*5.-uTime*3.4));
    x+=(n1-.5)*.3*y;
    float w=.3*(1.-y*.82)+.02;
    float body=1.-abs(x)/w;
    // Noise eats the flame from the top down, splitting it into tongues.
    float f=(body*1.15-y*.5-n2*.95*(.25+y))*smoothstep(0.,.07,y);
    float heat=clamp(f*1.25,0.,1.);
    float alpha=smoothstep(0.,.1,f);
    vec3 color=mix(vec3(.55,.06,.01),uColor,smoothstep(.0,.35,heat));
    color=mix(color,vec3(1.,.74,.2),smoothstep(.35,.7,heat));
    color=mix(color,vec3(1.,.96,.82),smoothstep(.75,1.,heat));
    gl_FragColor=vec4(color*(.35+heat*.85)*alpha*uPower,alpha*uPower);`,
  tornado: `
    vec2 p=vUv; float y=p.y, x=p.x-.5;
    float sway=sin(y*3.1+uTime*1.3)*.06*y;
    float radius=mix(.05,.42,pow(y,1.35));
    float rel=(x-sway)/radius;
    float body=1.-smoothstep(.72,1.,abs(rel));
    float swirl=fbm(vec2(rel*2.2-uTime*3.2+y*5., y*7.-uTime*.6)+uSeed);
    float bands=.55+.45*sin(rel*5.5+y*24.-uTime*9.+swirl*4.);
    float edgeLight=smoothstep(.35,1.,abs(rel))*body;
    float fadeY=smoothstep(0.,.06,y)*(1.-smoothstep(.9,1.,y));
    float alpha=body*fadeY*(.28+swirl*.45)*(.6+bands*.4);
    float debris=pow(fbm(vec2(x*18.+uTime*2.,y*10.)),4.)*(1.-smoothstep(0.,.25,y))*3.;
    vec3 color=mix(uColor*.42,uColor*1.05,bands*.6+edgeLight*.5);
    gl_FragColor=vec4(color*uPower,clamp(alpha+debris*.4,0.,.92)*uPower);`,
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
    ...(kind === 'mist' || kind === 'portalGlass' || kind === 'hole' || kind === 'tornado' ? {} : { blending: AdditiveBlending }),
  })
}

/** Dome shield lit by its silhouette, so it reads as a bubble from any side. */
export function shieldMaterial(color: string) {
  return new ShaderMaterial({
    name: 'cinematic-shield',
    uniforms: { uTime: { value: 0 }, uPower: { value: 1 }, uSeed: { value: 1 }, uProgress: { value: 0 }, uColor: { value: new Color(color) } },
    vertexShader: `varying vec3 vNormal, vView; varying vec3 vLocal;
      void main() { vLocal=position; vec4 p=modelViewMatrix*vec4(position,1.);
        vNormal=normalize(normalMatrix*normal); vView=normalize(-p.xyz); gl_Position=projectionMatrix*p; }`,
    fragmentShader: `varying vec3 vNormal, vView, vLocal; uniform float uTime,uPower,uSeed,uProgress; uniform vec3 uColor; ${ENERGY_NOISE}
      void main() {
        float facing=abs(dot(normalize(vNormal),normalize(vView)));
        float rim=pow(1.-facing,2.6);
        vec2 cell=vec2(atan(vLocal.z,vLocal.x)*3.2, vLocal.y*6.);
        vec2 hexa=abs(fract(cell+vec2(0.,floor(cell.x)*.5))-.5);
        float grid=smoothstep(.43,.49,max(hexa.x*1.15+hexa.y*.6,hexa.y*1.2));
        float ripple=pow(.5+.5*sin(vLocal.y*14.-uTime*4.+fbm(vLocal.xz*3.+uSeed)*3.),6.);
        float rise=smoothstep(0.,.35,uProgress*6.);
        float alpha=(rim*.85+grid*.07+ripple*.08*rim)*uPower*rise;
        gl_FragColor=vec4(mix(uColor,vec3(.85,.97,1.),rim*.6)*(1.+grid*.5)*uPower,alpha);
      }`,
    transparent: true, depthWrite: false, side: DoubleSide, blending: AdditiveBlending,
  })
}

export type SparkStyle = 'spark' | 'streak' | 'flake'

/** Round glowing sparks, thin falling streaks (rain) or soft unlit flakes. */
export function softSparkMaterial(color: string, size = .045, style: SparkStyle = 'spark') {
  const shape = style === 'streak'
    ? 'max(0.,1.-abs(q.x)*24.)*pow(max(0.,1.-abs(q.y)*2.),.7)*.45'
    : style === 'flake' ? 'smoothstep(.5,.2,length(q))*.8' : 'pow(max(0.,1.-length(q)*2.),2.)'
  const gain = style === 'spark' ? '3.' : style === 'streak' ? '1.2' : '.9'
  return new ShaderMaterial({
    name: 'cinematic-sparks',
    uniforms: { uColor: { value: new Color(color) }, uSize: { value: size }, uPower: { value: 1 } },
    vertexShader: `uniform float uSize;
      void main() { vec4 p=modelViewMatrix*vec4(position,1.);
      gl_PointSize=clamp(uSize*700./max(.1,-p.z),1.,${style === 'streak' ? 30 : 24}.);
      gl_Position=projectionMatrix*p; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uPower;
      void main() { vec2 q=gl_PointCoord-.5; float a=${shape};
      gl_FragColor=vec4(uColor*${gain}*uPower,a*uPower); }`,
    transparent: true, depthWrite: false, ...(style === 'flake' ? {} : { blending: AdditiveBlending }),
  })
}
