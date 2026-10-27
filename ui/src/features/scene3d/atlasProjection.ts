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

export const ATLAS_KEY = 'atlas-drape-3'

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
export function patchAtlasShader(shader: Shader, frame: AtlasFrame, faceOnly = false, useUv = false): void {
  shader.uniforms.atlasBody = { value: new Vector3(...frame.body) }
  shader.uniforms.atlasHead = { value: new Vector3(...(frame.head ?? [0, 1, 1e9])) }
  shader.uniforms.atlasFaceOnly = { value: faceOnly ? 1 : 0 }
  shader.uniforms.atlasUseUv = { value: useUv ? 1 : 0 }   // 1 while a face kit paints the material's own map (see `useMapUv`)
  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', '#include <common>\nvarying vec3 vAtlasPos;\nvarying vec3 vAtlasNormal;')
    .replace('#include <begin_vertex>', '#include <begin_vertex>\n\tvAtlasPos = position;\n\tvAtlasNormal = normal;')
  shader.fragmentShader = shader.fragmentShader
    .replace('#include <common>', '#include <common>\nvarying vec3 vAtlasPos;\nvarying vec3 vAtlasNormal;\nuniform vec3 atlasBody;\nuniform vec3 atlasHead;\nuniform float atlasFaceOnly;\nuniform float atlasUseUv;')
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
	// by the angle from the face, not by the normal: the painted face on its relief keeps the front picture whole, and the skull
	// round it fades from the front to the side picture between 53 and 75 degrees and to the back one between 112 and 140
	float faceYaw = atan( abs( atlasP.x ), atlasP.z );
	float crownK = smoothstep( 0.55, 0.85, abs( atlasN.y ) );
	float toSide = smoothstep( 0.92, 1.3, faceYaw ) * ( 1.0 - crownK );
	float toBack = smoothstep( 1.95, 2.45, faceYaw ) * ( 1.0 - crownK );
	vec4 frontTile = texture2D( map, vec2( ( 0.5 + atlasP.x / tileW ) / 3.0, headV ) );
	vec4 sideTile = texture2D( map, vec2( ( 1.5 - atlasP.z / tileW ) / 3.0, headV ) );
	vec4 backTile = texture2D( map, vec2( ( 2.5 - atlasP.x / tileW ) / 3.0, headV ) );
	vec4 headColor = mix( mix( frontTile, sideTile, toSide ), backTile, toBack );
	if ( atlasFaceOnly > 0.5 ) headColor = frontTile;
	float inHead = smoothstep( atlasHead.z - 0.008, atlasHead.z + 0.008, atlasP.y ) * ( 1.0 - smoothstep( tileW * 0.42, tileW * 0.49, max( abs( atlasP.x ), abs( atlasP.z ) ) ) );
	vec4 sampledDiffuseColor = mix( bodyColor, headColor, inHead );
	if ( atlasUseUv > 0.5 ) sampledDiffuseColor = texture2D( map, vMapUv );
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
      const faceOnly = material.name === 'face'
      material.onBeforeCompile = shader => {
        patchAtlasShader(shader as unknown as Shader, frame, faceOnly, material.userData.atlasUseUv === true)
        material.userData.atlasUniforms = shader.uniforms
      }
      material.customProgramCacheKey = () => (faceOnly ? `${ATLAS_KEY}-face` : ATLAS_KEY)
      material.needsUpdate = true
    }
  })
}

/** A face kit painted the material's own map (`faceDecal` mesh mode): sample it by the patch's UVs, not the atlas. ``on`` false goes back. */
export function useMapUv(material: Material, on: boolean): void {
  const uniforms = material.userData.atlasUniforms as Record<string, { value: unknown }> | undefined
  if (uniforms?.atlasUseUv) uniforms.atlasUseUv.value = on ? 1 : 0
  material.userData.atlasUseUv = on
}
