/** Word times from Hocus `POST /api/v1/audio/analyze` (lyrics_hint = script) on the Qwen WAVs. */
export type CutPaperVoiceWord = { text: string; start: number; end: number }

export type CutPaperVoiceAlign = {
  duration: number
  words: CutPaperVoiceWord[]
}

export const CUT_PAPER_VOICE_ALIGN: Record<string, CutPaperVoiceAlign> = {
  'nilo-1': {
    duration: 4.537,
    words: [
      { text: 'La', start: 0, end: 0.14 },
      { text: 'fuente', start: 0.14, end: 0.56 },
      { text: 'no', start: 0.56, end: 0.82 },
      { text: 'está', start: 0.82, end: 1.02 },
      { text: 'congelada', start: 1.02, end: 1.72 },
      { text: 'Alguien', start: 2.28, end: 2.66 },
      { text: 'le', start: 2.66, end: 2.72 },
      { text: 'pegó', start: 2.72, end: 3.02 },
      { text: 'un', start: 3.02, end: 3.08 },
      { text: 'cuadrado', start: 3.08, end: 3.54 },
      { text: 'de', start: 3.54, end: 3.66 },
      { text: 'papel', start: 3.66, end: 3.92 },
      { text: 'cebolla', start: 3.92, end: 4.44 },
    ],
  },
  'berta-1': {
    duration: 2.697,
    words: [
      { text: 'Pues', start: 0, end: 0.4 },
      { text: 'sabe', start: 0.4, end: 0.88 },
      { text: 'a', start: 0.88, end: 1.06 },
      { text: 'hielo', start: 1.06, end: 1.66 },
      { text: 'Lo', start: 1.92, end: 2.18 },
      { text: 'probé', start: 2.18, end: 2.62 },
    ],
  },
  'nilo-2': {
    duration: 1.737,
    words: [{ text: 'Berta, eso es cola.', start: 0, end: 1.737 }],
  },
  'berta-2': {
    duration: 2.457,
    words: [
      { text: 'Cola', start: 0, end: 0.38 },
      { text: 'fría', start: 0.38, end: 1.1 },
      { text: 'Como', start: 1.3, end: 1.64 },
      { text: 'hielo', start: 1.64, end: 2.32 },
    ],
  },
  'kito-1': {
    duration: 1.417,
    words: [
      { text: 'Era', start: 0, end: 0.3 },
      { text: 'un', start: 0.3, end: 0.52 },
      { text: 'sticker', start: 0.52, end: 0.96 },
    ],
  },
}

export type CutPaperLocale = 'es' | 'en'

export const CUT_PAPER_VOICE_ALIGN_EN: Record<string, CutPaperVoiceAlign> = {
  'nilo-1': {
    duration: 6.617,
    words: [
      { text: 'The', start: 0, end: 0.2 },
      { text: 'fountain', start: 0.2, end: 0.6 },
      { text: 'is', start: 0.6, end: 1.14 },
      { text: 'not', start: 1.14, end: 1.42 },
      { text: 'frozen', start: 1.42, end: 2.1 },
      { text: 'Someone', start: 2.98, end: 3.58 },
      { text: 'stuck', start: 3.58, end: 4.16 },
      { text: 'a', start: 4.16, end: 4.38 },
      { text: 'square', start: 4.38, end: 4.78 },
      { text: 'of', start: 4.78, end: 5.2 },
      { text: 'tracing', start: 5.2, end: 5.72 },
      { text: 'paper', start: 5.72, end: 6.08 },
      { text: 'on', start: 6.08, end: 6.46 },
      { text: 'it', start: 6.46, end: 6.58 },
    ],
  },
  'berta-1': {
    duration: 3.257,
    words: [
      { text: 'Well', start: 0, end: 0.28 },
      { text: 'it', start: 0.28, end: 0.64 },
      { text: 'tastes', start: 0.64, end: 0.98 },
      { text: 'like', start: 0.98, end: 1.32 },
      { text: 'ice', start: 1.32, end: 1.72 },
      { text: 'I', start: 2.38, end: 2.54 },
      { text: 'tried', start: 2.54, end: 2.88 },
      { text: 'it', start: 2.88, end: 3.08 },
    ],
  },
  'nilo-2': {
    duration: 1.817,
    words: [
      { text: 'Berta', start: 0, end: 0.9 },
      { text: "that's", start: 0.9, end: 1.14 },
      { text: 'glue', start: 1.28, end: 1.48 },
    ],
  },
  'berta-2': {
    duration: 2.617,
    words: [
      { text: 'Cold', start: 0, end: 0.36 },
      { text: 'glue', start: 0.36, end: 0.88 },
      { text: 'Like', start: 1.22, end: 1.88 },
      { text: 'ice', start: 1.88, end: 2.24 },
    ],
  },
  'kito-1': {
    duration: 1.177,
    words: [
      { text: 'It', start: 0, end: 0.18 },
      { text: 'was', start: 0.18, end: 0.36 },
      { text: 'a', start: 0.36, end: 0.46 },
      { text: 'sticker', start: 0.46, end: 0.8 },
    ],
  },
}

export function cutPaperLineEnd(lineId: string, start: number, locale: CutPaperLocale = 'es'): number {
  const table = locale === 'en' ? CUT_PAPER_VOICE_ALIGN_EN : CUT_PAPER_VOICE_ALIGN
  return start + table[lineId].duration
}

export function cutPaperVoiceFilename(speaker: string, lineId: string, locale: CutPaperLocale = 'es'): string {
  return locale === 'en' ? `vo-${speaker}-${lineId}-en.wav` : `vo-${speaker}-${lineId}.wav`
}

export function cutPaperDialogueBeats(
  line: { id: string; speaker: string; start: number; text: string },
  start = line.start,
  locale: CutPaperLocale = 'es',
) {
  const table = locale === 'en' ? CUT_PAPER_VOICE_ALIGN_EN : CUT_PAPER_VOICE_ALIGN
  const align = table[line.id]
  const units = align.words.length ? align.words : [{ text: line.text, start: 0, end: align.duration }]
  const mouths = ['closed', 'small', 'wide', 'round'].map(state => `puppet-${line.speaker}-mouth-${state}`)
  return units.map((word, index) => ({
    id: `${line.id}-${index}`,
    text: word.text,
    start: start + word.start,
    end: start + word.end,
    mouthLayerIds: mouths,
    audioTrackId: `vo-${line.id}`,
    confidence: 'aligned-audio' as const,
  }))
}
