import {
  DEFAULT_COMIC_CHAPTER_DIRECTION,
  DEFAULT_SHORT_FILM_DIRECTION,
  DEFAULT_TRAILER_DIRECTION,
  LEGACY_SPANISH_TRAILER_DIRECTION,
} from './adaptations'
import { DEFAULT_TRAILER_DURATION } from './trailerDefaults'
import type {
  StoryProductionRecipe,
  StoryProject,
  StoryTrailerFormat,
  StoryTrailerIntensity,
  StoryTrailerNarration,
  StoryTrailerSpoiler,
} from './types'

const TRAILER_FORMATS: readonly StoryTrailerFormat[] = ['theatrical', 'teaser', 'character']
const TRAILER_NARRATIONS: readonly StoryTrailerNarration[] = ['hybrid', 'voice_over', 'dialogue', 'visual']
const TRAILER_SPOILERS: readonly StoryTrailerSpoiler[] = ['mystery', 'balanced', 'revealing']
const TRAILER_INTENSITIES: readonly StoryTrailerIntensity[] = ['rising', 'relentless', 'prestige']
const MUSIC_MODES: readonly StoryProductionRecipe['musicProductionMode'][] = ['full', 'trailer']
const MUSIC_PACINGS: readonly StoryProductionRecipe['musicProductionPacing'][] = ['cinematic', 'balanced', 'rhythmic']

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function bounded(value: unknown, min: number, max: number, fallback: number): number {
  const next = Number(value)
  return Number.isFinite(next) ? Math.max(min, Math.min(max, next)) : fallback
}

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? value as T : fallback
}

export function defaultStoryProductionRecipe(): StoryProductionRecipe {
  return {
    filmDirection: DEFAULT_SHORT_FILM_DIRECTION,
    filmDurationSeconds: 45,
    filmPreserveVisualStyle: true,
    comicDirection: DEFAULT_COMIC_CHAPTER_DIRECTION,
    comicPageCount: 4,
    comicPanelsPerPage: 4,
    trailerDirection: DEFAULT_TRAILER_DIRECTION,
    trailerDurationSeconds: DEFAULT_TRAILER_DURATION,
    trailerFormat: 'theatrical',
    trailerNarration: 'hybrid',
    trailerSpoiler: 'balanced',
    trailerIntensity: 'rising',
    trailerTagline: '',
    trailerTitleCards: false,
    trailerPreserveVisualStyle: true,
    musicProductionMode: 'full',
    musicProductionPacing: 'balanced',
  }
}

export function normalizeStoryProductionRecipe(raw: unknown): StoryProductionRecipe {
  const fallback = defaultStoryProductionRecipe()
  const source = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  return {
    filmDirection: text(source.filmDirection, fallback.filmDirection),
    filmDurationSeconds: bounded(source.filmDurationSeconds, 10, 1800, fallback.filmDurationSeconds),
    filmPreserveVisualStyle: source.filmPreserveVisualStyle !== false,
    comicDirection: text(source.comicDirection, fallback.comicDirection),
    comicPageCount: bounded(source.comicPageCount, 1, 24, fallback.comicPageCount),
    comicPanelsPerPage: bounded(source.comicPanelsPerPage, 1, 12, fallback.comicPanelsPerPage),
    trailerDirection: source.trailerDirection === LEGACY_SPANISH_TRAILER_DIRECTION
      ? fallback.trailerDirection
      : text(source.trailerDirection, fallback.trailerDirection),
    trailerDurationSeconds: bounded(source.trailerDurationSeconds, 15, 180, fallback.trailerDurationSeconds),
    trailerFormat: pick(source.trailerFormat, TRAILER_FORMATS, fallback.trailerFormat),
    trailerNarration: pick(source.trailerNarration, TRAILER_NARRATIONS, fallback.trailerNarration),
    trailerSpoiler: pick(source.trailerSpoiler, TRAILER_SPOILERS, fallback.trailerSpoiler),
    trailerIntensity: pick(source.trailerIntensity, TRAILER_INTENSITIES, fallback.trailerIntensity),
    trailerTagline: text(source.trailerTagline),
    trailerTitleCards: source.trailerTitleCards === true,
    trailerPreserveVisualStyle: source.trailerPreserveVisualStyle !== false,
    musicProductionMode: pick(source.musicProductionMode, MUSIC_MODES, fallback.musicProductionMode),
    musicProductionPacing: pick(source.musicProductionPacing, MUSIC_PACINGS, fallback.musicProductionPacing),
  }
}

export function filmDurationOf(project: StoryProject): number {
  return project.projectType === 'quick_video'
    ? project.creativeBrief.durationSeconds
    : project.productionRecipe.filmDurationSeconds
}

export function filmDirectionOf(project: StoryProject): string {
  if (project.projectType === 'quick_video') {
    return project.creativeBrief.action.trim() || DEFAULT_SHORT_FILM_DIRECTION
  }
  return project.productionRecipe.filmDirection
}

export function trailerDurationOf(project: StoryProject): number {
  return project.projectType === 'trailer'
    ? project.creativeBrief.durationSeconds
    : project.productionRecipe.trailerDurationSeconds
}

export function patchStoryRecipe(
  project: StoryProject,
  recipe: Partial<StoryProductionRecipe>,
): Partial<StoryProject> {
  return { productionRecipe: { ...project.productionRecipe, ...recipe } }
}

export function patchFilmDuration(project: StoryProject, durationSeconds: number): Partial<StoryProject> {
  if (project.projectType === 'quick_video') {
    return { creativeBrief: { ...project.creativeBrief, durationSeconds } }
  }
  return patchStoryRecipe(project, { filmDurationSeconds: durationSeconds })
}

export function patchFilmDirection(project: StoryProject, filmDirection: string): Partial<StoryProject> {
  if (project.projectType === 'quick_video') {
    return { creativeBrief: { ...project.creativeBrief, action: filmDirection } }
  }
  return patchStoryRecipe(project, { filmDirection })
}

export function patchTrailerDuration(project: StoryProject, durationSeconds: number): Partial<StoryProject> {
  if (project.projectType === 'trailer') {
    return { creativeBrief: { ...project.creativeBrief, durationSeconds } }
  }
  return patchStoryRecipe(project, { trailerDurationSeconds: durationSeconds })
}
