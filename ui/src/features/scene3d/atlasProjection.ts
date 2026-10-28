/** A texture atlas draped over a body like cloth.
 *
 * A realistic lofted body (`blob_texture`) carries one picture: the body seen from the front and from behind, and the head at
 * three times the scale from the front, the side and the back. Choosing a view per triangle leaves hard seams (a face like a
 * cardboard mask). Here the picture is projected per pixel from the bind-pose position and normal, the views blended by how
 * the surface faces each one, so the texture turns round the form without a cut. The frame the views were drawn with comes
 * from the material's `extras.atlas` (glTF extras land in `userData`). */
import type { Material, Mesh, Object3D } from 'three'
import { Color, SRGBColorSpace, Vector3 } from 'three'

export type AtlasFrame = { body: [number, number, number]; head?: [number, number, number]; skin?: [number, number, number]; hold?: number; faceYaw?: number; faceFeather?: number; noUpperSplit?: boolean }

export const ATLAS_KEY = 'atlas-drape-7'

export function readAtlasFrame(userData: unknown): AtlasFrame | undefined {
  const raw = (userData as { atlas?: { body?: unknown; head?: unknown; skin?: unknown; hold?: unknown; faceYaw?: unknown; faceFeather?: unknown; noUpperSplit?: unknown } } | undefined)?.atlas
  const triple = (value: unknown): [number, number, number] | undefined =>
    Array.isArray(value) && value.length === 3 && value.every(item => typeof item === 'number' && Number.isFinite(item)) ? [value[0], value[1], value[2]] : undefined
  const body = triple(raw?.body)
  if (!body || body[2] <= 0) return undefined
  const head = triple(raw?.head)
  const skin = triple(raw?.skin)
  const hold = typeof raw?.hold === 'number' && Number.isFinite(raw.hold) && raw.hold >= -0.5 && raw.hold <= 1.2 ? raw.hold : undefined
  const degrees = (value: unknown, low: number, high: number) => typeof value === 'number' && Number.isFinite(value) && value >= low && value <= high ? value : undefined
  const faceYaw = degrees(raw?.faceYaw, 30, 58)
  const faceFeather = degrees(raw?.faceFeather, 0, 30)
  return { body, ...(raw?.noUpperSplit === true ? { noUpperSplit: true } : {}), ...(hold !== undefined ? { hold } : {}), ...(faceYaw !== undefined ? { faceYaw } : {}), ...(faceFeather ? { faceFeather } : {}), ...(head && head[1] > 0 ? { head } : {}), ...(skin && skin.every(value => value >= 0 && value <= 1) ? { skin } : {}) }
}

type Shader = { uniforms: Record<string, { value: unknown }>; vertexShader: string; fragmentShader: string }

/** The body and head tiles sampled from the bind pose and blended by the normal. Pure string work, so it is testable. */
export function patchAtlasShader(shader: Shader, frame: AtlasFrame, faceOnly = false, useUv = false): void {
  shader.uniforms.atlasBody = { value: new Vector3(...frame.body) }
  shader.uniforms.atlasHead = { value: new Vector3(...(frame.head ?? [0, 1, 1e9])) }
  shader.uniforms.atlasFaceOnly = { value: faceOnly ? 1 : 0 }
  const skin = frame.skin ? new Color().setRGB(frame.skin[0], frame.skin[1], frame.skin[2], SRGBColorSpace) : undefined
  shader.uniforms.atlasSkin = { value: new Vector3(skin?.r ?? 0, skin?.g ?? 0, skin?.b ?? 0) }
  shader.uniforms.atlasHasSkin = { value: skin ? 1 : 0 }
  shader.uniforms.atlasHold = { value: frame.hold ?? 0 }
  shader.uniforms.atlasSplit = { value: frame.noUpperSplit ? 0 : 1 }
  const patch = ((frame.faceYaw ?? 53) * Math.PI) / 180
  shader.uniforms.atlasPatchYaw = { value: patch }
  shader.uniforms.atlasFeather = { value: ((frame.faceFeather ?? 0) * Math.PI) / 180 }
  shader.uniforms.atlasUseUv = { value: useUv ? 1 : 0 }   // 1 while a face kit paints the material's own map (see `useMapUv`)
  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', '#include <common>\nvarying vec3 vAtlasPos;\nvarying vec3 vAtlasNormal;')
    .replace('#include <begin_vertex>', '#include <begin_vertex>\n\tvAtlasPos = position;\n\tvAtlasNormal = normal;')
  shader.fragmentShader = shader.fragmentShader
    .replace('#include <common>', '#include <common>\nvarying vec3 vAtlasPos;\nvarying vec3 vAtlasNormal;\nuniform vec3 atlasBody;\nuniform vec3 atlasHead;\nuniform float atlasFaceOnly;\nuniform float atlasUseUv;\nuniform vec3 atlasSkin;\nuniform float atlasHasSkin;\nuniform float atlasHold;\nuniform float atlasSplit;\nuniform float atlasPatchYaw;\nuniform float atlasFeather;')
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
	// above the brows the flank is hair: hair stretches well, while the side picture's forehead is bare skin, so the front picture is kept longer there
	float upperHead = smoothstep( 0.14, 0.24, ( atlasP.y - atlasHead.x ) / atlasHead.y ) * atlasSplit;
	float toSide = smoothstep( mix( atlasPatchYaw, atlasPatchYaw + 0.38 + atlasHold, upperHead ), mix( atlasPatchYaw + 0.38, atlasPatchYaw + 0.78 + atlasHold, upperHead ), faceYaw ) * ( 1.0 - crownK );
	float toBack = smoothstep( 1.95, 2.45, faceYaw ) * ( 1.0 - crownK );
	vec4 frontTile = texture2D( map, vec2( ( 0.5 + atlasP.x / tileW ) / 3.0, headV ) );
	vec4 sideTile = texture2D( map, vec2( ( 1.5 - atlasP.z / tileW ) / 3.0, headV ) );
	vec4 backTile = texture2D( map, vec2( ( 2.5 - atlasP.x / tileW ) / 3.0, headV ) );
	vec4 headColor = mix( mix( frontTile, sideTile, toSide ), backTile, toBack );
	if ( atlasFaceOnly > 0.5 ) headColor = frontTile;
	// what faces down (the underside of the jaw and the chin) takes the skin of the neck under the same x, not the row of the beard
	// that a front projection smears over it; the flat skin colour only fills in where the neck picture is missing
	float neckV = 0.9; // the row at 0.8 of the head tile's height: under the chin of a head picture, on the neck (as neck_skin reads it)
	vec4 neckTile = texture2D( map, vec2( ( 0.5 + clamp( atlasP.x, - tileW * 0.18, tileW * 0.18 ) / tileW ) / 3.0, neckV ) );
	float underside = smoothstep( -0.45, -0.8, atlasN.y ) * atlasHasSkin;
	headColor.rgb = mix( headColor.rgb, neckTile.rgb, underside );
	float inHead = smoothstep( atlasHead.z - 0.008, atlasHead.z + 0.008, atlasP.y ) * ( 1.0 - smoothstep( tileW * 0.42, tileW * 0.49, max( abs( atlasP.x ), abs( atlasP.z ) ) ) );
	vec4 sampledDiffuseColor = mix( bodyColor, headColor, inHead );
	if ( atlasUseUv > 0.5 ) sampledDiffuseColor = texture2D( map, vMapUv );
	diffuseColor *= sampledDiffuseColor;
	// the face patch fades into the skull over its last degrees, instead of ending on a ruled line
	if ( atlasFaceOnly > 0.5 && atlasFeather > 0.0 ) diffuseColor.a *= 1.0 - smoothstep( atlasPatchYaw - atlasFeather, atlasPatchYaw, faceYaw );
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
      if (faceOnly && frame.faceFeather) material.transparent = true
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
