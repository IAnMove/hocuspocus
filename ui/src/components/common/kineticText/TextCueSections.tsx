import { useEffect, useRef } from 'react'
import { useUiTranslation } from '../../../i18n'
import { paintKineticTexts, TEXT_ALIGNS, TEXT_BOX_KINDS, TEXT_ENTERS, TEXT_EXITS, TEXT_FONTS, TEXT_LOOPS, TEXT_WEIGHTS, type KineticText, type TextAlign, type TextBoxKind, type TextEnter, type TextExit, type TextFont, type TextLoop, type TextWeight } from '../../../lib/kineticText'
import { Choice, Field, fieldClass, NumberField } from './textFields'

export function TextCuePreview({ cue }: { cue: KineticText }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, 220, 64)
    ctx.fillStyle = '#10141f'
    ctx.fillRect(0, 0, 220, 64)
    const sample = { ...cue, x: 50, y: 50, size: 28, start: 0, end: 2 }
    paintKineticTexts(ctx, 220, 64, 0.7, [sample])
  }, [cue])
  return <canvas ref={canvas} width={220} height={64} className="mt-2 w-full rounded bg-[#10141f]" />
}

function options(prefix: string, values: readonly string[], label: (key: string) => string, blank?: string) {
  const items = values.map(value => ({ value, label: label(`${prefix}.${value}`) }))
  return blank ? [{ value: '', label: blank }, ...items] : items
}

export function TextCueContent({ cue, update }: { cue: KineticText; update: (patch: Partial<KineticText>) => void }) {
  const { t } = useUiTranslation('kineticText')
  return <details open className="rounded border border-border p-2">
    <summary className="cursor-pointer text-xs font-semibold">{t('sections.content')}</summary>
    <Field label={t('text')}><textarea maxLength={240} value={cue.text} onChange={event => update({ text: event.target.value })} className={fieldClass} /></Field>
    <div className="mt-2 grid grid-cols-2 gap-2">
      <NumberField label={t('start')} value={cue.start} step={.1} onChange={value => { if (value < cue.end) update({ start: value }) }} />
      <NumberField label={t('end')} value={cue.end} step={.1} onChange={value => { if (value > cue.start) update({ end: value }) }} />
      <NumberField label={t('x')} value={cue.x} onChange={value => update({ x: value })} />
      <NumberField label={t('y')} value={cue.y} onChange={value => update({ y: value })} />
      <NumberField label={t('size')} value={cue.size} onChange={value => update({ size: value })} />
      <NumberField label={t('rotation')} value={cue.rotation} onChange={value => update({ rotation: value })} />
    </div>
    <label className="mt-2 flex items-center gap-2 text-xs">{t('counter')}<input type="checkbox" checked={Boolean(cue.counter)} onChange={event => update({ counter: event.target.checked ? { from: 0, to: 10, decimals: 0, ease: 'ease' } : undefined })} /></label>
    {cue.counter ? <div className="mt-2 grid grid-cols-2 gap-2">
      <NumberField label={t('counterFrom')} value={cue.counter.from} onChange={value => update({ counter: { ...cue.counter!, from: value } })} />
      <NumberField label={t('counterTo')} value={cue.counter.to} onChange={value => update({ counter: { ...cue.counter!, to: value } })} />
      <NumberField label={t('counterDecimals')} value={cue.counter.decimals} onChange={value => update({ counter: { ...cue.counter!, decimals: value } })} />
      <Choice label={t('counterEase')} value={cue.counter.ease} options={[{ value: 'linear', label: t('eases.linear') }, { value: 'ease', label: t('eases.ease') }]} onChange={value => update({ counter: { ...cue.counter!, ease: value === 'ease' ? 'ease' : 'linear' } })} />
    </div> : null}
  </details>
}

export function TextCueStyle({ cue, update }: { cue: KineticText; update: (patch: Partial<KineticText>) => void }) {
  const { t } = useUiTranslation('kineticText')
  return <details className="rounded border border-border p-2">
    <summary className="cursor-pointer text-xs font-semibold">{t('sections.style')}</summary>
    <div className="mt-2 flex flex-wrap gap-3">
      <Choice label={t('font')} value={cue.font ?? 'sans'} options={TEXT_FONTS.map(font => ({ value: font, label: t(`fonts.${font}`) }))} onChange={value => update({ font: value as TextFont })} />
      <Choice label={t('weight')} value={String(cue.weight ?? 900)} options={TEXT_WEIGHTS.map(weight => ({ value: String(weight), label: String(weight) }))} onChange={value => update({ weight: Number(value) as TextWeight })} />
      <Choice label={t('align')} value={cue.align ?? 'center'} options={TEXT_ALIGNS.map(align => ({ value: align, label: t(`aligns.${align}`) }))} onChange={value => update({ align: value as TextAlign })} />
      <label className="flex items-center gap-2 text-xs">{t('color')}<input type="color" value={cue.color} onChange={event => update({ color: event.target.value })} /></label>
    </div>
    <div className="mt-2 grid grid-cols-2 gap-2">
      <NumberField label={t('maxWidth')} value={cue.maxWidth ?? 86} onChange={value => update({ maxWidth: value })} />
      <NumberField label={t('lineHeight')} value={cue.lineHeight ?? 1.12} step={.05} onChange={value => update({ lineHeight: value })} />
      <NumberField label={t('letterSpacing')} value={cue.letterSpacing ?? 0} step={.01} onChange={value => update({ letterSpacing: value })} />
    </div>
    <div className="mt-2 flex gap-4 text-xs">
      <label className="flex items-center gap-2"><input type="checkbox" checked={cue.uppercase === true} onChange={event => update({ uppercase: event.target.checked || undefined })} />{t('uppercase')}</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={cue.italic === true} onChange={event => update({ italic: event.target.checked || undefined })} />{t('italic')}</label>
    </div>
  </details>
}

export function TextCueMotion({ cue, update }: { cue: KineticText; update: (patch: Partial<KineticText>) => void }) {
  const { t } = useUiTranslation('kineticText')
  const blank = t('derived')
  const label = (key: string) => t(key as 'derived')
  return <details className="rounded border border-border p-2">
    <summary className="cursor-pointer text-xs font-semibold">{t('sections.motion')}</summary>
    <div className="mt-2 grid grid-cols-2 gap-2">
      <Choice label={t('preset')} value={cue.preset} options={options('presets', ['impact', 'rise', 'typewriter', 'wave'], label)} onChange={value => update({ preset: value as KineticText['preset'] })} />
      <Choice label={t('enter')} value={cue.enter?.preset ?? ''} options={options('enters', TEXT_ENTERS, label, blank)} onChange={value => update({ enter: value ? { preset: value as TextEnter, duration: cue.enter?.duration ?? .45 } : undefined })} />
      <NumberField label={t('duration')} value={cue.enter?.duration ?? .45} step={.05} onChange={value => update({ enter: { preset: cue.enter?.preset ?? 'fade', duration: value } })} />
      <Choice label={t('exit')} value={cue.exit?.preset ?? ''} options={options('exits', TEXT_EXITS, label, blank)} onChange={value => update({ exit: value ? { preset: value as TextExit, duration: cue.exit?.duration ?? .3 } : undefined })} />
      <NumberField label={t('exitDuration')} value={cue.exit?.duration ?? .3} step={.05} onChange={value => update({ exit: { preset: cue.exit?.preset ?? 'fade', duration: value } })} />
      <Choice label={t('loop')} value={cue.loop ?? ''} options={options('loops', TEXT_LOOPS, label, blank)} onChange={value => update({ loop: value ? value as TextLoop : undefined })} />
    </div>
  </details>
}

export function TextCueBox({ cue, update }: { cue: KineticText; update: (patch: Partial<KineticText>) => void }) {
  const { t } = useUiTranslation('kineticText')
  const box = cue.box ?? { kind: 'none' as TextBoxKind, color: '#1b140d', opacity: .9, padding: .35 }
  return <details className="rounded border border-border p-2">
    <summary className="cursor-pointer text-xs font-semibold">{t('sections.box')}</summary>
    <div className="mt-2 grid grid-cols-2 gap-2">
      <Choice label={t('box')} value={box.kind} options={TEXT_BOX_KINDS.map(kind => ({ value: kind, label: t(`boxKinds.${kind}`) }))} onChange={value => update({ box: value === 'none' ? undefined : { ...box, kind: value as TextBoxKind } })} />
      <label className="flex items-center gap-2 text-xs">{t('boxColor')}<input type="color" value={box.color} onChange={event => update({ box: { ...box, kind: box.kind === 'none' ? 'solid' : box.kind, color: event.target.value } })} /></label>
      <NumberField label={t('boxOpacity')} value={box.opacity} step={.05} onChange={value => update({ box: { ...box, opacity: value } })} />
      <NumberField label={t('boxPadding')} value={box.padding} step={.05} onChange={value => update({ box: { ...box, padding: value } })} />
    </div>
  </details>
}
