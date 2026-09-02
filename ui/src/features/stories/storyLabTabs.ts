import {
  BookOpen, Boxes, ChevronRight, Film, ImagePlus, Music, Network, Play, Sparkles, Users,
  type LucideIcon,
} from 'lucide-react'
import type { TFunction } from 'i18next'
import type { StoryLabTab } from './storyLabChrome'
import type { StoryProjectType } from './types'

export const STORY_PROJECT_TYPE_IDS: readonly StoryProjectType[] = [
  'full_story', 'music_video', 'trailer', 'quick_video',
]

type StoryLabT = TFunction<'storyLab'>
type TabLabelKey =
  | 'tabs.story' | 'tabs.assets' | 'tabs.images' | 'tabs.world' | 'tabs.characters'
  | 'tabs.music' | 'tabs.song' | 'tabs.relationships' | 'tabs.structure' | 'tabs.trailer'
  | 'tabs.createTrailer' | 'tabs.productions' | 'tabs.generate' | 'tabs.assembly'
  | 'tabs.musicVideo' | 'tabs.quickVideo'
type TabSpec = { id: StoryLabTab; labelKey: TabLabelKey; icon: LucideIcon }

const PROJECT_TYPE_COPY: Record<StoryProjectType, {
  label: `projectTypes.${StoryProjectType}.label`
  description: `projectTypes.${StoryProjectType}.description`
}> = {
  full_story: { label: 'projectTypes.full_story.label', description: 'projectTypes.full_story.description' },
  music_video: { label: 'projectTypes.music_video.label', description: 'projectTypes.music_video.description' },
  trailer: { label: 'projectTypes.trailer.label', description: 'projectTypes.trailer.description' },
  quick_video: { label: 'projectTypes.quick_video.label', description: 'projectTypes.quick_video.description' },
}

const FULL_STORY_TABS: TabSpec[] = [
  { id: 'overview', labelKey: 'tabs.story', icon: BookOpen },
  { id: 'assets', labelKey: 'tabs.assets', icon: ImagePlus },
  { id: 'world', labelKey: 'tabs.world', icon: Boxes },
  { id: 'characters', labelKey: 'tabs.characters', icon: Users },
  { id: 'music', labelKey: 'tabs.music', icon: Music },
  { id: 'relationships', labelKey: 'tabs.relationships', icon: Network },
  { id: 'structure', labelKey: 'tabs.structure', icon: ChevronRight },
  { id: 'trailer', labelKey: 'tabs.trailer', icon: Film },
  { id: 'productions', labelKey: 'tabs.productions', icon: Film },
  { id: 'assembly', labelKey: 'tabs.assembly', icon: Play },
]

const MUSIC_VIDEO_TABS: TabSpec[] = [
  { id: 'overview', labelKey: 'tabs.musicVideo', icon: Film },
  { id: 'assets', labelKey: 'tabs.images', icon: ImagePlus },
  { id: 'music', labelKey: 'tabs.song', icon: Music },
  { id: 'trailer', labelKey: 'tabs.trailer', icon: Film },
  { id: 'productions', labelKey: 'tabs.generate', icon: Sparkles },
  { id: 'assembly', labelKey: 'tabs.assembly', icon: Play },
]

const TRAILER_TABS: TabSpec[] = [
  { id: 'overview', labelKey: 'tabs.trailer', icon: Film },
  { id: 'assets', labelKey: 'tabs.images', icon: ImagePlus },
  { id: 'trailer', labelKey: 'tabs.createTrailer', icon: Sparkles },
  { id: 'assembly', labelKey: 'tabs.assembly', icon: Play },
]

const QUICK_VIDEO_TABS: TabSpec[] = [
  { id: 'overview', labelKey: 'tabs.quickVideo', icon: Film },
  { id: 'assets', labelKey: 'tabs.images', icon: ImagePlus },
  { id: 'trailer', labelKey: 'tabs.trailer', icon: Film },
  { id: 'productions', labelKey: 'tabs.generate', icon: Sparkles },
  { id: 'assembly', labelKey: 'tabs.assembly', icon: Play },
]

const TABS_BY_TYPE: Record<StoryProjectType, TabSpec[]> = {
  full_story: FULL_STORY_TABS,
  music_video: MUSIC_VIDEO_TABS,
  trailer: TRAILER_TABS,
  quick_video: QUICK_VIDEO_TABS,
}

export function storyProjectTypes(t: StoryLabT): Array<{
  id: StoryProjectType
  label: string
  description: string
}> {
  return STORY_PROJECT_TYPE_IDS.map(id => ({
    id,
    label: t(PROJECT_TYPE_COPY[id].label),
    description: t(PROJECT_TYPE_COPY[id].description),
  }))
}

export function storyLabTabs(
  projectType: StoryProjectType,
  t: StoryLabT,
): Array<{ id: StoryLabTab; label: string; icon: LucideIcon }> {
  return TABS_BY_TYPE[projectType].map(item => ({
    id: item.id,
    label: t(item.labelKey),
    icon: item.icon,
  }))
}
