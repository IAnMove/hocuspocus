import { Mesh, PlaneGeometry, ShaderMaterial, type Texture } from 'three'

export type ImageFootprint = { bottom: number; center: number; width: number }

/** Ignore faint antialiasing and use the lowest opaque band, not the PNG canvas. */
export function imageFootprint(rgba: ArrayLike<number>, width: number, height: number): ImageFootprint | null {
  let bottom = -1
  for (let y = height - 1; y >= 0 && bottom < 0; y--) {
    for (let x = 0; x < width; x++) if (rgba[(y * width + x) * 4 + 3] >= 128) { bottom = y; break }
  }
  if (bottom < 0) return null
  let left = width, right = -1
  const band = Math.max(1, Math.round(height * .06))
  for (let y = Math.max(0, bottom - band); y <= bottom; y++) {
    for (let x = 0; x < width; x++) if (rgba[(y * width + x) * 4 + 3] >= 128) { left = Math.min(left, x); right = Math.max(right, x) }
  }
  return { bottom: (height - 1 - bottom) / height, center: (left + right + 1) / (2 * width), width: (right - left + 1) / width }
}

export function textureFootprint(texture: Texture | null): ImageFootprint | null {
  const image = texture?.image as (CanvasImageSource & { width: number; height: number }) | undefined
  if (!image?.width || !image.height || typeof document === 'undefined') return null
  try {
    const canvas = document.createElement('canvas'), ratio = Math.min(1, 384 / Math.max(image.width, image.height))
    canvas.width = Math.max(1, Math.round(image.width * ratio)); canvas.height = Math.max(1, Math.round(image.height * ratio))
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return null
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
    return imageFootprint(ctx.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height)
  } catch { return null } // An external image may not grant canvas readback.
}

/** A soft contact patch lies on the same ground plane as the visible feet. */
export function imageContactShadow(foot: ImageFootprint, aspect: number, opacity: number) {
  const width = Math.max(.25, foot.width * aspect * 2.1)
  const material = new ShaderMaterial({ transparent: true, depthWrite: false, toneMapped: false,
    uniforms: { opacity: { value: opacity } },
    vertexShader: 'varying vec2 patchUv; void main(){patchUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader: 'varying vec2 patchUv; uniform float opacity; void main(){float r=length(patchUv*2.-1.);float a=pow(1.-smoothstep(0.,1.,r),1.6)*opacity;gl_FragColor=vec4(0.,0.,0.,a);}',
  })
  const shadow = new Mesh(new PlaneGeometry(width * 1.8, Math.max(.35, width * .9)), material)
  shadow.name = 'image-contact-shadow'
  shadow.rotation.x = -Math.PI / 2
  shadow.position.set((foot.center - .5) * 2 * aspect, -.996, 0)
  return shadow
}
