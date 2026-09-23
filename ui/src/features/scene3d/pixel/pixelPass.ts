import { Vector2 } from 'three'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'
import type { PixelWorld } from './pixelWorld'

/** Final pass: sample one colour per art pixel, then quantize it with
 *  ordered dithering, so 3D actors, screens and effects share the pixel
 *  art look of the painted world. Runs on display colours, after output. */
export function createPixelPass() {
  const pass = new ShaderPass({
    name: 'PixelArtShader',
    uniforms: { tDiffuse: { value: null }, uResolution: { value: new Vector2(1280, 720) }, uSize: { value: 3 }, uLevels: { value: 24 }, uDither: { value: .6 } },
    vertexShader: 'varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }',
    fragmentShader: `uniform sampler2D tDiffuse; uniform vec2 uResolution; uniform float uSize, uLevels, uDither; varying vec2 vUv;
      float bayer4(vec2 p){ vec2 q=mod(p,4.); float i=q.y*4.+q.x;
        return (i==0.?0.:i==1.?8.:i==2.?2.:i==3.?10.:i==4.?12.:i==5.?4.:i==6.?14.:i==7.?6.:i==8.?3.:i==9.?11.:i==10.?1.:i==11.?9.:i==12.?15.:i==13.?7.:i==14.?13.:5.)/16.; }
      void main(){
        vec2 cell=floor(vUv*uResolution/uSize);
        vec3 c=texture2D(tDiffuse,(cell+.5)*uSize/uResolution).rgb;
        float steps=uLevels-1.;
        c=floor(clamp(c,0.,1.)*steps+.5+(bayer4(cell)-.5)*uDither)/steps;
        gl_FragColor=vec4(clamp(c,0.,1.),1.);
      }`,
  })
  pass.enabled = false
  return pass
}

export function syncPixelPass(pass: ShaderPass, pixel: PixelWorld | undefined, width: number, height: number) {
  pass.enabled = Boolean(pixel && (pixel.pixelSize > 1 || pixel.levels < 64))
  if (!pixel) return
  pass.uniforms.uResolution.value.set(width, height)
  // Art pixels scale with the frame, so previews and 1080p exports match.
  pass.uniforms.uSize.value = Math.max(1, pixel.pixelSize * height / 720)
  pass.uniforms.uLevels.value = pixel.levels
  pass.uniforms.uDither.value = pixel.dither
}
