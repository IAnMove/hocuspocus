import i18n from '../i18n'

/** Known server preset labels. An unknown id or label stays as the server sent it. */
const PRESET_KEYS: Record<string, string> = {
  Auto: 'resolutionPresets.auto',
  auto: 'resolutionPresets.auto',
  '480p': 'resolutionPresets.p480',
  '540p': 'resolutionPresets.p540',
  '720p': 'resolutionPresets.p720',
  '768p': 'resolutionPresets.p768',
  '1080p': 'resolutionPresets.p1080',
  '480p · fastest': 'resolutionPresets.fastest480',
  '540p · validated': 'resolutionPresets.validated540',
  '720p · aligned': 'resolutionPresets.aligned720',
  '768p · maximum Base canvas': 'resolutionPresets.maxBase768',
}

/** Translated name for a resolution preset. The server string is unchanged. */
export function resolutionPresetLabel(id: string, serverLabel?: string | null) {
  const key = (serverLabel && PRESET_KEYS[serverLabel]) || PRESET_KEYS[id]
  if (!key) return serverLabel || id
  return String(i18n.t(key, serverLabel || id, { ns: 'studio' }))
}
