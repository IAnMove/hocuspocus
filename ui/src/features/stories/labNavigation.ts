import type { AgentSeriesSection, AgentStorySection } from '../../lib/uiBus'
import type { StoryProjectType } from './types'
import { storyLabTabIds } from './storyLabTabs'
import type { StoryLabTab } from './storyLabChrome'

export const STORY_LAB_SECTIONS: readonly AgentStorySection[] = [
  'overview', 'assets', 'world', 'characters', 'relationships', 'structure',
  'music', 'trailer', 'productions', 'assembly',
]

export const SERIES_LAB_SECTIONS: readonly AgentSeriesSection[] = [
  'setup', 'canon', 'episode', 'shots', 'review',
]

const STORY_SECTION_ALIASES: Record<string, AgentStorySection> = {
  overview: 'overview',
  assets: 'assets',
  world: 'world',
  characters: 'characters',
  relationships: 'relationships',
  structure: 'structure',
  music: 'music',
  trailer: 'trailer',
  productions: 'productions',
  assembly: 'assembly',
  story: 'overview',
  images: 'assets',
  song: 'music',
  generate: 'productions',
  universe: 'world',
  script: 'structure',
  audio: 'music',
  results: 'assembly',
  concept: 'overview',
}

const SERIES_SECTION_ALIASES: Record<string, AgentSeriesSection> = {
  setup: 'setup',
  canon: 'canon',
  episode: 'episode',
  shots: 'shots',
  review: 'review',
  bible: 'canon',
  preparation: 'setup',
}

const COMPACT_SECTIONS = new Set<AgentStorySection>([
  'world', 'characters', 'relationships', 'structure',
])

export type StoryLabNavigationResolution =
  | {
    ok: true
    requested: AgentStorySection
    tab: StoryLabTab
    anchor: string
    equivalent: boolean
  }
  | {
    ok: false
    requested: string
    reason: string
  }

export type SeriesLabNavigationResolution =
  | { ok: true; requested: AgentSeriesSection; tab: AgentSeriesSection; equivalent: boolean }
  | { ok: false; requested: string; reason: string }

export function canonicalizeStoryLabSection(raw: string): AgentStorySection | null {
  return STORY_SECTION_ALIASES[raw.trim().toLowerCase()] || null
}

export function canonicalizeSeriesLabSection(raw: string): AgentSeriesSection | null {
  return SERIES_SECTION_ALIASES[raw.trim().toLowerCase()] || null
}

function compactAnchor(section: AgentStorySection): string {
  if (section === 'structure') return 'story-review-structure'
  if (section === 'characters' || section === 'relationships') return 'story-review-characters'
  return 'story-review-world'
}

function equivalent(
  requested: AgentStorySection,
  tab: StoryLabTab,
  anchor: string,
): Extract<StoryLabNavigationResolution, { ok: true }> {
  return { ok: true, requested, tab, anchor, equivalent: true }
}

export function resolveStoryLabNavigation(
  requested: string,
  projectType: StoryProjectType,
): StoryLabNavigationResolution {
  const section = canonicalizeStoryLabSection(requested)
  if (!section) {
    return { ok: false, requested, reason: `Story Lab has no section called “${requested}”.` }
  }
  const visible = storyLabTabIds(projectType)
  if (visible.includes(section)) {
    return {
      ok: true,
      requested: section,
      tab: section,
      anchor: `story-review-${section}`,
      equivalent: false,
    }
  }
  if (projectType === 'full_story') {
    if (section === 'characters' || section === 'relationships' || section === 'assets') {
      return equivalent(section, 'world', section === 'assets' ? 'story-review-assets' : `story-review-${section}`)
    }
    if (section === 'trailer') return equivalent(section, 'productions', 'story-review-trailer')
  }
  if (projectType !== 'full_story' && COMPACT_SECTIONS.has(section)) {
    return equivalent(section, 'overview', compactAnchor(section))
  }
  if ((projectType === 'music_video' || projectType === 'quick_video') && section === 'assets') {
    return equivalent(section, 'overview', 'story-review-world')
  }
  if (projectType === 'trailer' && section === 'productions') {
    return equivalent(section, 'trailer', 'story-review-trailer')
  }
  if ((projectType === 'music_video' || projectType === 'quick_video') && section === 'trailer') {
    return equivalent(section, 'productions', 'story-review-overview')
  }
  return {
    ok: false,
    requested: section,
    reason: `Story Lab → ${section} is not visible for a ${projectType} project.`,
  }
}

export function resolveSeriesLabNavigation(requested: string): SeriesLabNavigationResolution {
  const section = canonicalizeSeriesLabSection(requested)
  if (!section) {
    return { ok: false, requested, reason: `Series Lab has no section called “${requested}”.` }
  }
  return { ok: true, requested: section, tab: section, equivalent: false }
}

export function describeStoryLabNavigation(resolution: Extract<StoryLabNavigationResolution, { ok: true }>): string {
  if (!resolution.equivalent) return `I opened Story Lab → ${resolution.tab}.`
  return `I opened Story Lab → ${resolution.tab}, where ${resolution.requested} lives for this project type.`
}

export function describeSeriesLabNavigation(resolution: Extract<SeriesLabNavigationResolution, { ok: true }>): string {
  return `I opened Series Lab → ${resolution.tab}.`
}
