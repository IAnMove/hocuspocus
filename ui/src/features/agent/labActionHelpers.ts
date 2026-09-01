import { useStore } from '../../stores/useStore'
import type { AgentCreativeCharacter, AgentCreativeLocation } from './agentActions'

export const normalizeName = (value: string): string => value
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/[^a-zA-Z0-9]+/g, ' ')
  .trim()
  .toLowerCase()

export const boundedDuration = (value: number | undefined, fallback: number): number => (
  Math.max(15, Math.min(3_600, Math.round(value || fallback)))
)

export const explicitMusicLanguage = (value: string): string => {
  const raw = value.trim()
  const aliases: Record<string, string> = {
    es: 'Español', en: 'English', fr: 'Français', de: 'Deutsch',
    it: 'Italiano', pt: 'Português', ja: '日本語', ko: '한국어', zh: '中文',
  }
  return aliases[raw.toLowerCase()] || raw || 'Español'
}

export function creativeCharacters(values: AgentCreativeCharacter[]): AgentCreativeCharacter[] {
  return values.length ? values : [{
    name: 'Protagonista',
    role: 'Protagonista',
    personality: 'Ingenioso, curioso y decidido.',
    desire: 'Resolver el conflicto central.',
    flaw: 'Se precipita cuando cree tener razón.',
    appearance: 'Silueta clara, vestuario reconocible y expresiones legibles.',
    voice: 'Natural, expresiva y coherente con el tono.',
  }]
}

export function creativeLocations(values: AgentCreativeLocation[]): AgentCreativeLocation[] {
  return values.length ? values : [{
    name: 'Escenario principal',
    purpose: 'Reunir a los personajes y hacer visible el conflicto.',
    description: 'Un lugar reconocible, visualmente coherente y con espacio para la acción.',
  }]
}

export function outlineBeats(values: string[], premise: string, ending: string): string[] {
  if (values.length >= 3) return values
  return [
    `Inicio: ${premise || 'se presenta el deseo del protagonista y aparece una complicación.'}`,
    'Desarrollo: el plan inicial empeora el conflicto y obliga a los personajes a cambiar de estrategia.',
    `Final: ${ending || 'la decisión final resuelve el problema con una consecuencia clara y memorable.'}`,
  ]
}

export function showLab(filter: 'stories' | 'series'): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setMediaFilter(filter)
  state.setSidebarOpen(false)
}
