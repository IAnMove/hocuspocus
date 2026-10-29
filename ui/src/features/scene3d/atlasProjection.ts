/** A texture atlas draped over a body like cloth.
 *
 * A realistic lofted body (`blob_texture`) carries one picture: the body seen from the front and from behind, and the head at
 * three times the scale from the front, the side and the back. Choosing a view per triangle leaves hard seams (a face like a
 * cardboard mask). Here the picture is projected per pixel from the bind-pose position and normal, the views blended by how
 * the surface faces each one, so the texture turns round the form without a cut. The frame the views were drawn with comes
 * from the material's `extras.atlas` (glTF extras land in `userData`). */
import type { Material, Mesh, Object3D } from 'three'
import { Vector3 } from 'three'

export type AtlasFrame = { body: [number, number, number]; head?: [number, number, number] }

export const ATLAS_KEY = 'atlas-drape-1'

export function readAtlasFrame(userData: unknown): AtlasFrame | undefined {
  const raw = (userData as { atlas?: { body?: unknown; head?: unknown } } | undefined)?.atlas
  const triple = (value: unknown): [number, number, number] | undefined =>
    Array.isArray(value) && value.length === 3 && value.every(item => typeof item === 'number' && Number.isFinite(item)) ? [value[0], value[1], value[2]] : undefined
  const body = triple(raw?.body)
  if (!body || body[2] <= 0) return undefined
  const head = triple(raw?.head)
  return { body, ...(head && head[1] > 0 ? { head } : {}) }
}

type Shader = { uniforms: Record<string, { value: unknown }>; vertexShader: string; fragmentShader: string }

/** The body and head tiles sampled from the bind pose and blended by the normal. Pure string work, so it is testable. */
export function patchAtlasShader(shader: Shader, frame: AtlasFrame): void {
  shader.uniforms.atlasBody = { value: new Vector3(...frame.body) }
  shader.uniforms.atlasHead = { value: new Vector3(...(frame.head ?? [0, 1, 1e9])) }
  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', '#include <common>\nvarying vec3 vAtlasPos;\nvarying vec3 vAtlasNormal;')
    .replace('#include <begin_vertex>', '#include <begin_vertex>\n\tvAtlasPos = position;\n\tvAtlasNormal = normal;')
  shader.fragmentShader = shader.fragmentShader
    .replace('#include <common>', '#include <common>\nvarying vec3 vAtlasPos;\nvarying vec3 vAtlasNormal;\nuniform vec3 atlasBody;\nuniform vec3 atlasHead;')
    .replace('#include <map_fragment>', `#ifdef USE_MAP
	vec3 atlasN = normalize( vAtlasNormal );
	vec3 atlasP = vAtlasPos;
	float bodyU = 0.5 + ( atlasP.x - atlasBody.x ) / atlasBody.z;
	float bodyV = ( 0.5 - ( atlasP.y - atlasBody.y ) / atlasBody.z ) * 0.5;
	float frontWeight = pow( max( atlasN.z, 0.0 ), 3.0 ) + 0.02;
	float backWeight = pow( max( -atlasN.z, 0.0 ), 3.0 ) + 0.02;
	vec4 bodyColor = ( texture2D( map, vec2( bodyU * 0.5, bodyV ) ) * frontWeight + texture2D( map, vec2( ( 1.0 - bodyU ) * 0.5 + 0.5, bodyV ) ) * backWeight ) / ( frontWeight + backWeight );
	float tileW = atlasHead.y / 1.5;
	float headV = 0.5 + ( 0.5 - ( atlasP.y - atlasHead.x ) / atlasHead.y ) * 0.5;
	float crown = pow( abs( atlasN.y ), 3.0 );
	float hf = pow( max( atlasN.z, 0.0 ), 8.0 ) + crown + 0.002;
	float hb = pow( max( -atlasN.z, 0.0 ), 8.0 ) + 0.002;
	float hs = pow( abs( atlasN.x ), 8.0 ) + 0.002;
	vec4 headColor = ( texture2D( map, vec2( ( 0.5 + atlasP.x / tileW ) / 3.0, headV ) ) * hf
		+ texture2D( map, vec2( ( 1.5 - atlasP.z / tileW ) / 3.0, headV ) ) * hs
		+ texture2D( map, vec2( ( 2.5 - atlasP.x / tileW ) / 3.0, headV ) ) * hb ) / ( hf + hs + hb );
	float inHead = smoothstep( atlasHead.z - 0.008, atlasHead.z + 0.008, atlasP.y ) * ( 1.0 - smoothstep( tileW * 0.42, tileW * 0.49, max( abs( atlasP.x ), abs( atlasP.z ) ) ) );
	vec4 sampledDiffuseColor = mix( bodyColor, headColor, inHead );
	diffuseColor *= sampledDiffuseColor;
#endif`)
}

/** Give the materials a loaded model carries an atlas frame for the drape; the rest are left alone. */
export function applyAtlasProjection(root: Object3D): void {
  root.traverse(object => {
    const mesh = object as Mesh
    if (!mesh.isMesh) return
    for (const item of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      const material = item as Material & { map?: unknown }
      if (!material || material.userData.atlasDrape || !material.map) continue
      const frame = readAtlasFrame(material.userData)
      if (!frame) continue
      material.userData.atlasDrape = true
      material.onBeforeCompile = shader => patchAtlasShader(shader as unknown as Shader, frame)
      material.customProgramCacheKey = () => ATLAS_KEY
      material.needsUpdate = true
    }
  })
}
