import i18n from '../../i18n'
import { CATALOG_VERSION, type SceneTemplateDefinition } from './catalog'
import { APPROVED_REFERENCE_JSON } from './approvedReferences'
import { parseRenderedReferenceScene } from './previewSnapshot'

/** Offline user-selected download, not an arbitrary remote proxy. Check the
 * exact published bytes before interpreting the saved scene or loading assets. */
export async function verifyReferenceBytes(bytes: ArrayBuffer, expected: { bytes: number; sha256: string }) {
  if (bytes.byteLength !== expected.bytes) throw new Error(i18n.t('scene3d:templateErrors.sizeMismatch'))
  if (!globalThis.crypto?.subtle) throw new Error(i18n.t('scene3d:templateErrors.shaNeedsContext'))
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  const sha256 = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
  if (sha256 !== expected.sha256) throw new Error(i18n.t('scene3d:templateErrors.jsonChanged'))
}

export async function importApprovedReference(file: Pick<File, 'size' | 'arrayBuffer'>, template: SceneTemplateDefinition) {
  const expected = APPROVED_REFERENCE_JSON[template.id]
  if (!expected || file.size !== expected.bytes) throw new Error(i18n.t('scene3d:templateErrors.sizeMismatch'))
  const bytes = await file.arrayBuffer()
  await verifyReferenceBytes(bytes, expected)
  return parseRenderedReferenceScene(JSON.parse(new TextDecoder().decode(bytes)), {
    id: template.id, version: template.version, catalogVersion: CATALOG_VERSION, variant: 'coral',
  })
}
