import { FACE_RIG_PRESET_ROOT, type FaceRigMouthPresetPack } from '../../lib/characterKitFaceRig'
import { CHARACTER_MOUTH_STATES } from '../../lib/characterMouthStates'

/** Export ordinary PNGs + a manifest; no user character images or voice data. */
export async function downloadMouthPacks(packs: FaceRigMouthPresetPack[]) {
  const { default: JSZip } = await import('jszip')
  const archive = new JSZip()
  for (const pack of packs) for (const state of CHARACTER_MOUTH_STATES) {
    const file = pack.states[state]?.file
    if (!file) continue
    if (!/^[a-z0-9-]+\/[a-z]+\.png$/.test(file)) throw new Error('Invalid mouth pack asset.')
    const response = await fetch(`${FACE_RIG_PRESET_ROOT}/${file}`)
    if (!response.ok) throw new Error('The mouth pack could not be downloaded.')
    archive.file(file, await response.blob())
  }
  archive.file('manifest.json', JSON.stringify({ version: 1, states: CHARACTER_MOUTH_STATES, packs }, null, 2))
  const readme = await fetch(`${FACE_RIG_PRESET_ROOT}/STUDIO-20.txt`)
  if (!readme.ok) throw new Error('The mouth pack instructions could not be downloaded.')
  archive.file('README.txt', await readme.text())
  const url = URL.createObjectURL(await archive.generateAsync({ type: 'blob', compression: 'DEFLATE' }))
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = packs.length === 1 ? `${packs[0].id}-mouths.zip` : 'hocuspocus-20-mouth-styles.zip'
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}
