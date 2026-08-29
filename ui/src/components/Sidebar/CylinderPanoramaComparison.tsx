import { useEffect, useRef, useState } from 'react'
import { createCylinderPanoramaShaders } from '../../lib/cylinderPanorama'

const compile = (gl: WebGL2RenderingContext, type: number, source: string) => {
  const shader = gl.createShader(type)
  if (!shader) throw new Error('Could not create a WebGL shader.')
  gl.shaderSource(shader, source); gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || 'Cylinder shader failed to compile.')
  return shader
}

/** Deliberately preview-only A/B test for a repeating panorama. */
export function CylinderPanoramaComparison({ source, onClose }: { source: string; onClose: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [rotation, setRotation] = useState(0)
  const [fov, setFov] = useState(75)
  const [error, setError] = useState<string | null>(null)
  const rotationRef = useRef(rotation)
  const fovRef = useRef(fov)
  rotationRef.current = rotation
  fovRef.current = fov

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const gl = canvas.getContext('webgl2', { alpha: false, antialias: true })
    if (!gl) { setError('WebGL2 is unavailable here; use the existing parallax renderer.'); return }
    let program: WebGLProgram | null = null
    let texture: WebGLTexture | null = null
    try {
      const shaders = createCylinderPanoramaShaders()
      const vertex = compile(gl, gl.VERTEX_SHADER, shaders.vertex)
      const fragment = compile(gl, gl.FRAGMENT_SHADER, shaders.fragment)
      program = gl.createProgram()
      if (!program) throw new Error('Could not create the cylinder program.')
      gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program)
      gl.deleteShader(vertex); gl.deleteShader(fragment)
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) || 'Cylinder program failed to link.')
      const buffer = gl.createBuffer()
      if (!buffer) throw new Error('Could not create cylinder geometry.')
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW)
      gl.useProgram(program)
      const position = gl.getAttribLocation(program, 'aPosition')
      gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0)
      texture = gl.createTexture()
      if (!texture) throw new Error('Could not create panorama texture.')
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texture)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
      const image = new Image()
      image.onload = () => {
        gl.bindTexture(gl.TEXTURE_2D, texture)
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true)
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image)
        gl.uniform1i(gl.getUniformLocation(program!, 'uPanorama'), 0)
        const render = () => {
          const width = Math.max(1, Math.round(canvas.clientWidth * devicePixelRatio))
          const height = Math.max(1, Math.round(canvas.clientHeight * devicePixelRatio))
          if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height }
          gl.viewport(0, 0, width, height)
          gl.uniform1f(gl.getUniformLocation(program!, 'uHorizontalRotation'), rotationRef.current)
          gl.uniform1f(gl.getUniformLocation(program!, 'uVerticalFov'), fovRef.current)
          gl.uniform1f(gl.getUniformLocation(program!, 'uAspect'), width / height)
          gl.drawArrays(gl.TRIANGLES, 0, 6)
        }
        render()
        ;(canvas as HTMLCanvasElement & { __cylinderRender?: () => void }).__cylinderRender = render
      }
      image.onerror = () => setError('Could not load this panorama image for WebGL comparison.')
      image.src = source
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Cylinder comparison failed.') }
    return () => { if (texture) gl.deleteTexture(texture); if (program) gl.deleteProgram(program) }
  }, [source])

  useEffect(() => { (canvasRef.current as (HTMLCanvasElement & { __cylinderRender?: () => void }) | null)?.__cylinderRender?.() }, [rotation, fov])

  return <div className="space-y-2 rounded border border-cyan-300/35 bg-cyan-400/[.04] p-2">
    <div className="flex items-center justify-between gap-2"><span className="text-[10px] font-medium text-cyan-100">Environment A/B · parallax vs cylinder</span><button type="button" onClick={onClose} className="text-[9px] text-text-muted hover:text-text-primary">Close</button></div>
    <p className="text-[8px] leading-relaxed text-text-muted">Preview only — it never changes or exports the scene. Cylinder is appropriate only for a horizontally seamless panorama and a centred camera; otherwise keep parallax.</p>
    <div className="grid grid-cols-2 gap-1.5"><div><span className="mb-0.5 block text-[8px] text-text-muted">Current flat layer</span><img src={source} alt="Flat parallax reference" className="aspect-video w-full rounded border border-border object-cover" /></div><div><span className="mb-0.5 block text-[8px] text-text-muted">Inside cylinder</span><canvas ref={canvasRef} className="aspect-video w-full rounded border border-cyan-300/30 bg-black" /></div></div>
    <div className="grid grid-cols-2 gap-2"><label className="text-[8px] text-text-muted">Rotation {rotation}°<input type="range" min="-180" max="180" value={rotation} onChange={event => setRotation(Number(event.target.value))} className="mt-0.5 w-full" /></label><label className="text-[8px] text-text-muted">Vertical FOV {fov}°<input type="range" min="30" max="120" value={fov} onChange={event => setFov(Number(event.target.value))} className="mt-0.5 w-full" /></label></div>
    {error && <p className="text-[8px] text-amber-200">{error}</p>}
  </div>
}
