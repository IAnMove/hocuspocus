import classes from '../../../../../app/shared/scene_effect_classes.json' with { type: 'json' }

type Entry = { class: 'presence' | 'hit'; duration?: number }
const EFFECTS = classes.effects as Record<string, Entry>

/** What an `fx` cue of this kind lasts when the script gives no `duration` (services/series_fx_classes.py): `'shot'` for a
 * presence effect, the table's seconds for a hit, 1 for a kind the table does not list. */
export function defaultFxLength(kind: unknown): 'shot' | number {
  const entry = typeof kind === 'string' ? EFFECTS[kind] : undefined
  if (!entry) return 1
  return entry.class === 'hit' ? entry.duration ?? 1 : 'shot'
}
