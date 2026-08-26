export const SEAM_OCCLUDER_KINDS = ['pole', 'lamp', 'tree', 'column'] as const
export type SeamOccluderKind = (typeof SEAM_OCCLUDER_KINDS)[number]

export type SeamOccluderConfig = {
  enabled: boolean
  kind: SeamOccluderKind
  scale: number
  opacity: number
}

type StripLike = {
  enabled?: boolean
  count?: number
  spacing?: number
  direction?: 'up' | 'down' | 'left' | 'right'
  speed?: number
  phase?: number
}

const isKind = (value: unknown): value is SeamOccluderKind =>
  typeof value === 'string' && (SEAM_OCCLUDER_KINDS as readonly string[]).includes(value)

/** Pick a silhouette that belongs to the place, not a random prop. */
export function suggestSeamOccluderKind(text = ''): SeamOccluderKind {
  const hay = text.toLowerCase()
  if (/(train|station|street|city|alley|urban|metro|lamp|farola|andén|anden)/.test(hay)) return 'lamp'
  if (/(forest|wood|tree|jungle|park|grove|bosque|selva|árbol|arbol)/.test(hay)) return 'tree'
  if (/(temple|palace|column|ruin|hall|pillar|columna|templo|palacio)/.test(hay)) return 'column'
  return 'pole'
}

export function normalizeSeamOccluder(value: unknown, fallback: SeamOccluderConfig = { enabled: false, kind: 'pole', scale: 1, opacity: .82 }): SeamOccluderConfig {
  if (!value || typeof value !== 'object') return fallback
  const raw = value as { enabled?: unknown; kind?: unknown; scale?: unknown; opacity?: unknown }
  return {
    enabled: raw.enabled === true,
    kind: isKind(raw.kind) ? raw.kind : fallback.kind,
    scale: typeof raw.scale === 'number' && Number.isFinite(raw.scale) ? Math.max(.45, Math.min(1.8, raw.scale)) : fallback.scale,
    opacity: typeof raw.opacity === 'number' && Number.isFinite(raw.opacity) ? Math.max(.2, Math.min(1, raw.opacity)) : fallback.opacity,
  }
}

/** Occluders sit on tile joins: half a spacing ahead of the repeating plate. */
export function seamOccluderPhase(strip: StripLike): number {
  return Number(strip.phase ?? 0) + Number(strip.spacing ?? 100) / 2
}

function svgMarkup(kind: SeamOccluderKind): string {
  const paths = {
    lamp: '<rect x="36" y="210" width="8" height="490" rx="3"/><path d="M18 188c0-28 18-52 42-52s42 24 42 52c0 8-4 14-10 18H28c-6-4-10-10-10-18z"/><rect x="28" y="198" width="44" height="18" rx="6"/><circle cx="40" cy="176" r="7"/><circle cx="56" cy="176" r="7"/>',
    tree: '<rect x="36" y="430" width="10" height="270" rx="3"/><ellipse cx="41" cy="250" rx="38" ry="86"/><ellipse cx="28" cy="310" rx="32" ry="70"/><ellipse cx="54" cy="300" rx="30" ry="64"/>',
    column: '<rect x="22" y="668" width="36" height="18" rx="2"/><rect x="28" y="160" width="24" height="510" rx="3"/><rect x="18" y="142" width="44" height="22" rx="3"/><rect x="24" y="128" width="32" height="16" rx="2"/>',
    pole: '<rect x="37" y="120" width="7" height="560" rx="3"/><rect x="32" y="108" width="17" height="16" rx="3"/>',
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 720" preserveAspectRatio="xMidYMax meet"><g fill="#0c0e14">${paths[kind]}</g></svg>`
}

export function seamOccluderDataUri(kind: SeamOccluderKind): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgMarkup(kind))}`
}

export function paintSeamOccluder(
  context: CanvasRenderingContext2D,
  kind: SeamOccluderKind,
  frameWidth: number,
  frameHeight: number,
  scale = 1,
) {
  const safeScale = Math.max(.45, Math.min(1.8, scale))
  const width = frameWidth * 0.085 * safeScale
  const height = frameHeight * 0.94 * safeScale
  context.save()
  context.fillStyle = '#0c0e14'
  context.translate(-width / 2, -height / 2)
  const x = width * 0.45
  if (kind === 'lamp') {
    context.fillRect(x, height * 0.28, width * 0.1, height * 0.7)
    context.beginPath()
    context.ellipse(x + width * 0.05, height * 0.24, width * 0.42, height * 0.08, 0, 0, Math.PI * 2)
    context.fill()
    context.fillRect(x - width * 0.28, height * 0.265, width * 0.66, height * 0.028)
  } else if (kind === 'tree') {
    context.fillRect(x, height * 0.58, width * 0.12, height * 0.4)
    context.beginPath()
    context.ellipse(x + width * 0.06, height * 0.34, width * 0.48, height * 0.28, 0, 0, Math.PI * 2)
    context.fill()
    context.beginPath()
    context.ellipse(x - width * 0.08, height * 0.42, width * 0.38, height * 0.22, 0, 0, Math.PI * 2)
    context.fill()
    context.beginPath()
    context.ellipse(x + width * 0.2, height * 0.4, width * 0.34, height * 0.2, 0, 0, Math.PI * 2)
    context.fill()
  } else if (kind === 'column') {
    context.fillRect(x - width * 0.18, height * 0.97, width * 0.5, height * 0.03)
    context.fillRect(x - width * 0.04, height * 0.22, width * 0.28, height * 0.74)
    context.fillRect(x - width * 0.16, height * 0.19, width * 0.52, height * 0.035)
    context.fillRect(x - width * 0.1, height * 0.165, width * 0.4, height * 0.028)
  } else {
    context.fillRect(x, height * 0.16, width * 0.09, height * 0.8)
    context.fillRect(x - width * 0.06, height * 0.145, width * 0.21, height * 0.025)
  }
  context.restore()
}
