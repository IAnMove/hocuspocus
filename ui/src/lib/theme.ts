import type { ParseKeys } from 'i18next'

/**
 * Theme management for Maestro.
 *
 * Themes are CSS-variable overrides applied via `[data-theme="..."]` on
 * the <html> element. The actual variable values live in src/index.css.
 *
 * The user-facing model is a list of theme families (HocusPocus Blue,
 * Classic, Onyx, plus the community palettes below), each with a dark and
 * a light variant, plus an appearance mode:
 *   - mode: 'dark' | 'light' | 'auto' — auto follows the OS scheme
 *     (prefers-color-scheme) and live-switches when the OS changes.
 * The effective CSS theme = the chosen family's variant for whichever
 * scheme the mode resolves to. The light variant ids (ivory, daylight,
 * pearl, latte, lotus, ...) are internal CSS ids, not user-facing names:
 * the picker only ever shows the family label.
 *
 * Persistence: localStorage under "maestro-theme-mode" and
 * "maestro-theme-family". Legacy keys are migrated on first load so
 * nobody's chosen look changes: the original single-theme key
 * ("maestro-theme", may hold a light variant id) and the short-lived
 * per-variant key ("maestro-theme-dark") both seed the family. An
 * inline script in index.html applies the resolved theme to <html>
 * before React mounts so there's no flash of the default theme.
 *
 * Adding a new family: add `[data-theme]` blocks for both variants in
 * index.css, add the family to FAMILIES below, and extend the maps in
 * the index.html pre-mount script.
 */

export type ThemeId =
  | 'default' | 'golden-hour' | 'onyx' | 'ivory' | 'daylight' | 'pearl'
  | 'tokyo-night' | 'tokyo-day'
  | 'catppuccin' | 'latte'
  | 'gruvbox' | 'gruvbox-day'
  | 'everforest' | 'everforest-day'
  | 'rose-pine' | 'rose-pine-dawn'
  | 'kanagawa' | 'lotus'
  | 'nord' | 'nord-day'
  | 'solarized' | 'solarized-day'
  | 'dracula' | 'alucard'
  | 'ayu' | 'ayu-day'
  | 'one' | 'one-day'
  | 'amiga' | 'workbench'
  | 'phosphor' | 'phosphor-day'
  | 'studio' | 'studio-day'
export type FamilyId =
  | 'default' | 'golden-hour' | 'onyx'
  | 'tokyo-night' | 'catppuccin' | 'gruvbox' | 'everforest'
  | 'rose-pine' | 'kanagawa' | 'nord'
  | 'solarized' | 'dracula' | 'ayu' | 'one'
  | 'amiga' | 'phosphor' | 'studio'
export type ThemeMode = 'dark' | 'light' | 'auto'

export interface ThemeVariant {
  /** The [data-theme] id this variant renders as. */
  id: ThemeId
  /** Three-color preview swatch shown in the settings picker. */
  swatch: { bg: string; surface: string; accent: string }
}

export interface ThemeFamily {
  id: FamilyId
  dark: ThemeVariant
  light: ThemeVariant
}

/* FAMILIES ordering doubles as the dropdown order. The Classic
 * family's id stays 'default' (despite no longer being the default)
 * so localStorage values from users who explicitly chose it don't
 * break — only the LABEL says 'Classic'. */

/** Settings copy for a theme family. Brand names stay in both languages. */
export function themeTextKey(id: FamilyId, part: 'label' | 'description') {
  return `appearance.themes.${id}.${part}` as ParseKeys<'settings'>
}

export const FAMILIES: ThemeFamily[] = [
  {
    id: 'golden-hour',
    dark: { id: 'golden-hour', swatch: { bg: '#050505', surface: '#121212', accent: '#2563eb' } },
    light: { id: 'ivory', swatch: { bg: '#f1f5f9', surface: '#ffffff', accent: '#1d4ed8' } },
  },
  {
    id: 'default',
    dark: { id: 'default', swatch: { bg: '#0a0a0f', surface: '#1a1a25', accent: '#3b82f6' } },
    light: { id: 'daylight', swatch: { bg: '#f4f5f7', surface: '#fafbfc', accent: '#2563eb' } },
  },
  {
    id: 'onyx',
    dark: { id: 'onyx', swatch: { bg: '#000000', surface: '#1a1a1a', accent: '#aaaaaa' } },
    light: { id: 'pearl', swatch: { bg: '#f2f2f2', surface: '#f9f9f9', accent: '#525252' } },
  },
  /* Community palettes. Ordered calmest-first among themselves: this app
   * is mostly a wall of thumbnails, and a saturated chrome steals colour
   * from the content, which is a cost a terminal palette never pays. */
  {
    id: 'everforest',
    dark: { id: 'everforest', swatch: { bg: '#272e33', surface: '#343f44', accent: '#a7c080' } },
    light: { id: 'everforest-day', swatch: { bg: '#f4f0d9', surface: '#fffbef', accent: '#8da101' } },
  },
  {
    id: 'gruvbox',
    dark: { id: 'gruvbox', swatch: { bg: '#1d2021', surface: '#32302f', accent: '#fabd2f' } },
    light: { id: 'gruvbox-day', swatch: { bg: '#f2e5bc', surface: '#f9f5d7', accent: '#b57614' } },
  },
  {
    id: 'nord',
    dark: { id: 'nord', swatch: { bg: '#242933', surface: '#3b4252', accent: '#88c0d0' } },
    light: { id: 'nord-day', swatch: { bg: '#e5e9f0', surface: '#ffffff', accent: '#5e81ac' } },
  },
  {
    id: 'tokyo-night',
    dark: { id: 'tokyo-night', swatch: { bg: '#16161e', surface: '#24283b', accent: '#7aa2f7' } },
    light: { id: 'tokyo-day', swatch: { bg: '#e1e2e7', surface: '#f2f2f5', accent: '#2e7de9' } },
  },
  {
    id: 'catppuccin',
    dark: { id: 'catppuccin', swatch: { bg: '#11111b', surface: '#1e1e2e', accent: '#cba6f7' } },
    light: { id: 'latte', swatch: { bg: '#eff1f5', surface: '#ffffff', accent: '#8839ef' } },
  },
  {
    id: 'rose-pine',
    dark: { id: 'rose-pine', swatch: { bg: '#191724', surface: '#26233a', accent: '#c4a7e7' } },
    light: { id: 'rose-pine-dawn', swatch: { bg: '#faf4ed', surface: '#ffffff', accent: '#907aa9' } },
  },
  {
    id: 'studio',
    dark: { id: 'studio', swatch: { bg: '#1c1c1c', surface: '#2b2b2b', accent: '#35b0c9' } },
    light: { id: 'studio-day', swatch: { bg: '#d6d6d6', surface: '#f0f0f0', accent: '#10697c' } },
  },
  {
    id: 'phosphor',
    dark: { id: 'phosphor', swatch: { bg: '#0a0800', surface: '#1a1400', accent: '#ffb000' } },
    light: { id: 'phosphor-day', swatch: { bg: '#efe6cf', surface: '#fdf8ea', accent: '#8a5f00' } },
  },
  {
    id: 'amiga',
    dark: { id: 'amiga', swatch: { bg: '#003c72', surface: '#0055aa', accent: '#ff8800' } },
    light: { id: 'workbench', swatch: { bg: '#a0a0a0', surface: '#c8c8c8', accent: '#0a3d91' } },
  },
  {
    id: 'solarized',
    dark: { id: 'solarized', swatch: { bg: '#002b36', surface: '#073642', accent: '#268bd2' } },
    light: { id: 'solarized-day', swatch: { bg: '#fdf6e3', surface: '#fffdf5', accent: '#14567f' } },
  },
  {
    id: 'one',
    dark: { id: 'one', swatch: { bg: '#21252b', surface: '#2f343d', accent: '#61afef' } },
    light: { id: 'one-day', swatch: { bg: '#f0f0f0', surface: '#ffffff', accent: '#2f60cc' } },
  },
  {
    id: 'ayu',
    dark: { id: 'ayu', swatch: { bg: '#0b0e14', surface: '#131721', accent: '#e6b450' } },
    light: { id: 'ayu-day', swatch: { bg: '#f4f4f4', surface: '#ffffff', accent: '#a35200' } },
  },
  {
    id: 'dracula',
    dark: { id: 'dracula', swatch: { bg: '#21222c', surface: '#343746', accent: '#bd93f9' } },
    light: { id: 'alucard', swatch: { bg: '#fffbeb', surface: '#ffffff', accent: '#644ac9' } },
  },
  {
    id: 'kanagawa',
    dark: { id: 'kanagawa', swatch: { bg: '#16161d', surface: '#2a2a37', accent: '#e6c384' } },
    light: { id: 'lotus', swatch: { bg: '#f2ecbc', surface: '#fffcea', accent: '#4d699b' } },
  },
]

/** Any theme id (either variant) -> its family. */
const FAMILY_OF: Record<ThemeId, FamilyId> = {
  'golden-hour': 'golden-hour',
  ivory: 'golden-hour',
  default: 'default',
  daylight: 'default',
  onyx: 'onyx',
  pearl: 'onyx',
  'tokyo-night': 'tokyo-night',
  'tokyo-day': 'tokyo-night',
  catppuccin: 'catppuccin',
  latte: 'catppuccin',
  gruvbox: 'gruvbox',
  'gruvbox-day': 'gruvbox',
  everforest: 'everforest',
  'everforest-day': 'everforest',
  'rose-pine': 'rose-pine',
  'rose-pine-dawn': 'rose-pine',
  kanagawa: 'kanagawa',
  lotus: 'kanagawa',
  nord: 'nord',
  'nord-day': 'nord',
  solarized: 'solarized',
  'solarized-day': 'solarized',
  dracula: 'dracula',
  alucard: 'dracula',
  ayu: 'ayu',
  'ayu-day': 'ayu',
  one: 'one',
  'one-day': 'one',
  amiga: 'amiga',
  workbench: 'amiga',
  phosphor: 'phosphor',
  'phosphor-day': 'phosphor',
  studio: 'studio',
  'studio-day': 'studio',
}

const LIGHT_IDS: ReadonlySet<string> = new Set([
  'ivory', 'daylight', 'pearl',
  'tokyo-day', 'latte', 'gruvbox-day', 'everforest-day',
  'rose-pine-dawn', 'lotus', 'nord-day',
  'solarized-day', 'alucard', 'ayu-day', 'one-day',
  'workbench', 'phosphor-day', 'studio-day',
])

export interface ThemePrefs {
  mode: ThemeMode
  family: FamilyId
}

const MODE_KEY = 'maestro-theme-mode'
const FAMILY_KEY = 'maestro-theme-family'
/** Short-lived key from the interim two-picker build; holds a dark id. */
const INTERIM_DARK_KEY = 'maestro-theme-dark'
/** Original single-theme key; may hold either variant. Still written
 * with the resolved theme so downgrades show something sensible. */
const LEGACY_KEY = 'maestro-theme'

const DEFAULT_PREFS: ThemePrefs = { mode: 'dark', family: 'golden-hour' }

function isFamily(id: string | null): id is FamilyId {
  return !!id && FAMILIES.some(f => f.id === id)
}

export function getStoredPrefs(): ThemePrefs {
  try {
    const legacyRaw = localStorage.getItem(LEGACY_KEY)
    const legacy = legacyRaw && legacyRaw in FAMILY_OF ? (legacyRaw as ThemeId) : null

    const modeRaw = localStorage.getItem(MODE_KEY)
    const mode: ThemeMode =
      modeRaw === 'dark' || modeRaw === 'light' || modeRaw === 'auto'
        ? modeRaw
        // Migration: a stored light variant means the user chose light.
        : legacy && LIGHT_IDS.has(legacy) ? 'light' : 'dark'

    const familyRaw = localStorage.getItem(FAMILY_KEY)
    const interimDark = localStorage.getItem(INTERIM_DARK_KEY)
    const family: FamilyId = isFamily(familyRaw)
      ? familyRaw
      : isFamily(interimDark) ? interimDark
      : legacy ? FAMILY_OF[legacy]
      : DEFAULT_PREFS.family

    return { mode, family }
  } catch {
    /* localStorage may be blocked (private mode, etc.) */
    return { ...DEFAULT_PREFS }
  }
}

/** Is the OS currently asking for a light scheme? */
export function osPrefersLight(): boolean {
  try {
    return window.matchMedia('(prefers-color-scheme: light)').matches
  } catch {
    return false
  }
}

/** The variant ('dark' | 'light') the given prefs resolve to right now. */
export function resolveVariant(prefs: ThemePrefs): 'dark' | 'light' {
  return prefs.mode === 'light' || (prefs.mode === 'auto' && osPrefersLight())
    ? 'light'
    : 'dark'
}

/** The CSS theme id that should actually render for the given prefs. */
export function resolveTheme(prefs: ThemePrefs): ThemeId {
  const fam = FAMILIES.find(f => f.id === prefs.family) ?? FAMILIES[0]
  return fam[resolveVariant(prefs)].id
}

/* Last-applied prefs + a lazily-registered OS-scheme listener so that
 * mode 'auto' live-switches when the OS flips (e.g. scheduled dark
 * mode at sunset) without a reload. Module-level singleton — the
 * listener stays for the page lifetime. */
let _current: ThemePrefs | null = null
let _listenerInstalled = false
const _changeSubs = new Set<() => void>()

function installOsListener(): void {
  if (_listenerInstalled) return
  _listenerInstalled = true
  try {
    const mq = window.matchMedia('(prefers-color-scheme: light)')
    mq.addEventListener('change', () => {
      if (_current?.mode === 'auto') {
        applyResolvedTheme(_current)
        _changeSubs.forEach(fn => fn())
      }
    })
  } catch {
    /* matchMedia unavailable — auto degrades to dark */
  }
}

/** Subscribe to effective-theme changes caused by the OS (auto mode).
 * Returns an unsubscribe function. */
export function onOsThemeChange(fn: () => void): () => void {
  _changeSubs.add(fn)
  return () => { _changeSubs.delete(fn) }
}

function applyResolvedTheme(prefs: ThemePrefs): void {
  const id = resolveTheme(prefs)
  const html = document.documentElement
  if (id === 'default') {
    html.removeAttribute('data-theme')
  } else {
    html.setAttribute('data-theme', id)
  }
  // Keep mobile browser chrome (address bar tint) in sync with the
  // page background. The pre-mount script in index.html does the same
  // for cold loads.
  const meta = document.querySelector('meta[name="theme-color"]')
  const fam = FAMILIES.find(f => f.id === prefs.family) ?? FAMILIES[0]
  const swatch = fam[resolveVariant(prefs)].swatch
  if (meta) meta.setAttribute('content', swatch.bg)
  // Briefly enable transitions so the swap is animated. Remove the
  // class after the transition finishes so theme tokens elsewhere
  // (e.g. progress-bar fills, range-slider thumbs) don't pay the
  // 200ms transition cost on every interaction.
  html.classList.add('theme-transition')
  window.setTimeout(() => html.classList.remove('theme-transition'), 250)
}

export function applyThemePrefs(prefs: ThemePrefs): void {
  _current = prefs
  installOsListener()
  applyResolvedTheme(prefs)
  try {
    localStorage.setItem(MODE_KEY, prefs.mode)
    localStorage.setItem(FAMILY_KEY, prefs.family)
    // Keep the legacy key pointing at the resolved theme so a
    // downgrade to an older build still shows something sensible.
    localStorage.setItem(LEGACY_KEY, resolveTheme(prefs))
  } catch {
    /* localStorage blocked — theme still applies for this session */
  }
}
