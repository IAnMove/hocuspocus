import type { AspectRatio, ModelOptions, ResolutionPreset } from '../types'

const resolutionMap: Record<ResolutionPreset, Record<AspectRatio, string>> = {
  'auto': {
    'auto': 'auto',
    '21:9': 'auto',
    '16:9': 'auto',
    '9:16': 'auto',
    '1:1': 'auto',
    '4:3': 'auto',
    '3:4': 'auto',
  },
  '480p': {
    'auto': 'auto_480p',
    '21:9': '1120x480',
    '16:9': '848x480',
    '9:16': '480x848',
    '1:1': '672x672',
    '4:3': '736x544',
    '3:4': '544x736',
  },
  '540p': {
    'auto': 'auto_540p',
    '21:9': '1280x544',
    '16:9': '960x544',
    '9:16': '544x960',
    '1:1': '736x736',
    '4:3': '832x608',
    '3:4': '608x832',
  },
  '720p': {
    'auto': 'auto_720p',
    '21:9': '1664x704',
    '16:9': '1280x720',
    '9:16': '720x1280',
    '1:1': '1024x1024',
    '4:3': '1104x832',
    '3:4': '832x1104',
  },
  '768p': {
    'auto': 'auto_768p',
    '21:9': '1792x768',
    '16:9': '1344x768',
    '9:16': '768x1344',
    '1:1': '768x768',
    '4:3': '1024x768',
    '3:4': '768x1024',
  },
  '1080p': {
    'auto': 'auto_1080p',
    '21:9': '2560x1088',
    '16:9': '1920x1088',
    '9:16': '1088x1920',
    '1:1': '1024x1024',
    '4:3': '1920x1088',
    '3:4': '1088x1920',
  },
}

export function resolveResolution(
  modelOptions: ModelOptions | null,
  preset: ResolutionPreset,
  ratio: AspectRatio,
): string {
  const modelValues = modelOptions?.resolution_presets?.[preset]?.values
  return modelValues?.[ratio]
    || modelValues?.['16:9']
    || resolutionMap[preset]?.[ratio]
    || resolutionMap[preset]?.['16:9']
    || '1280x720'
}

export function findResolutionSelection(
  resolution: string,
  modelOptions: ModelOptions | null,
): { preset: ResolutionPreset; ratio: AspectRatio } | null {
  const maps: Array<Partial<Record<ResolutionPreset, { values: Partial<Record<AspectRatio, string>> }>>> = []
  if (modelOptions?.resolution_presets) maps.push(modelOptions.resolution_presets)
  maps.push(Object.fromEntries(
    Object.entries(resolutionMap).map(([preset, values]) => [preset, { values }]),
  ) as Partial<Record<ResolutionPreset, { values: Partial<Record<AspectRatio, string>> }>>)

  for (const presetMap of maps) {
    for (const [preset, config] of Object.entries(presetMap)) {
      for (const [ratio, value] of Object.entries(config?.values || {})) {
        if (value === resolution) {
          return {
            preset: preset as ResolutionPreset,
            ratio: ratio as AspectRatio,
          }
        }
      }
    }
  }
  return null
}
