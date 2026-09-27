import type { ModelResourceRequirements } from '../types'

/**
 * Community MiniMax Music 3 ports. These are deliberately informational:
 * they use different runtimes and are not selectable until an adapter has
 * been installed and validated by HocusPocus.
 */
export interface CommunityMusicModel {
  id: string
  name: string
  format: string
  sourceUrl: string
  requirements: ModelResourceRequirements
}

export const MINIMAX_MUSIC_COMMUNITY_MODELS: CommunityMusicModel[] = [
  {
    id: 'minimax_music3_gguf',
    name: 'MiniMax Music 3 · GGUF (community)',
    format: 'GGML/GGUF · C++/CUDA/ROCm/Vulkan',
    sourceUrl: 'https://github.com/ServeurpersoCom/minimaxmusic.cpp',
    requirements: {
      storage_gb: 13,
      vram_gb: 9,
      platform: 'CUDA, ROCm, Vulkan o CPU',
      backend: 'minimaxmusic.cpp / GGML',
      tier: 'experimental',
      note: 'Figures published by the community implementation; not compatible with our Diffusers backend.',
    },
  },
  {
    id: 'minimax_music3_mlx',
    name: 'MiniMax Music 3 · MLX 8-bit (community)',
    format: 'MLX · Apple Silicon',
    sourceUrl: 'https://github.com/appautomaton/mlx-minimax-music3',
    requirements: {
      storage_gb: 10,
      platform: 'macOS · Apple Silicon',
      backend: 'MLX',
      tier: 'experimental',
      note: 'Requires a separate MLX adapter; does not work as a CUDA checkpoint.',
    },
  },
  {
    id: 'minimax_music3_webgpu',
    name: 'MiniMax Music 3 · WebGPU (community)',
    format: 'WebGPU · Chromium browser',
    sourceUrl: 'https://huggingface.co/hyung778/minimax-music3-webgpu',
    requirements: {
      storage_gb: 8,
      vram_gb: 12,
      platform: 'Chromium 151+ · WebGPU · shader-f16',
      backend: 'WebGPU in the browser',
      tier: 'experimental',
      note: '12 GB for songs up to one minute; 16 GB for full capacity.',
    },
  },
]

export function modelRequirementsText(requirements?: ModelResourceRequirements): string {
  if (!requirements) return ''
  const parts: string[] = []
  if (requirements.vram_gb != null) parts.push(`VRAM ~${requirements.vram_gb} GB`)
  if (requirements.storage_gb != null) parts.push(`disco ~${requirements.storage_gb} GB`)
  if (requirements.ram_gb != null) parts.push(`RAM ~${requirements.ram_gb} GB`)
  if (requirements.platform) parts.push(requirements.platform)
  if (requirements.backend) parts.push(`backend: ${requirements.backend}`)
  if (requirements.note) parts.push(requirements.note)
  return parts.join(' · ')
}
