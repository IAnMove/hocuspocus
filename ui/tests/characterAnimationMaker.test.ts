import assert from 'node:assert/strict'
import test from 'node:test'
import { aspectOf, keptPoses, makeAnimation, type PoseTake } from '../src/features/characters/characterAnimationMaker.ts'
import { animationDef } from '../src/lib/characterAnimations.ts'
import { createCharacterKit } from '../src/lib/characterKit.ts'

const kit = () => ({
  ...createCharacterKit('Ana'), lookNotes: 'a detective in a mustard coat',
  base: { id: 'ana-base', name: 'Ana', source: '/api/v1/file/ana.png?workspace=w', kind: 'image' as const, alphaStatus: 'transparent' as const, reviewState: 'approved' as const },
  provenance: [{ method: 'character-style-create', style: 'paper-cutout' }],
})

function deps(log: string[], options: { failOn?: string } = {}) {
  let seed = 100
  return {
    seed: () => seed++,
    prompt: async (details: { animation: string; pose: string; description?: string; style?: string }) => {
      log.push(`prompt ${details.animation}/${details.pose} ${details.style} ${details.description}`)
      return { prompt: `prompt-${details.pose}`, negative: 'neg', screen: 'green' as const, resolution: '896x1152' }
    },
    generate: async (_provider: string, prompt: string, model: string, _reference: unknown, negative: string, request?: Record<string, unknown>) => {
      log.push(`generate ${prompt} ${model} ${negative} ${request?.seed} ${JSON.stringify(request?.references)} ${request?.referenceMode} ${request?.resolution} ${request?.aspectRatio}`)
      if (prompt === `prompt-${options.failOn}`) throw new Error('out of memory')
      return { source: `/api/v1/file/raw-${prompt}.png?workspace=w` } as never
    },
    key: async (details: { source: string; mode: string; intentId?: string }) => {
      log.push(`key ${details.source} ${details.mode} ${details.intentId}`)
      return { file: 'k.png', url: `${details.source.replace('raw', 'keyed')}`, sha256: 'x' }
    },
    sheet: async (details: { workspace: string; sources: string[]; name?: string }) => {
      log.push(`sheet ${details.workspace} ${details.name} ${details.sources.join(',')}`)
      return { filename: 's.png', source: '/api/v1/file/walk-sheet-1.png?workspace=w', width: 1480, height: 640, count: details.sources.length, columns: details.sources.length, rows: 1,
               cell: { width: 370, height: 640 }, feet: .96, figure: .86 }
    },
  }
}

test('every pose is made in turn from the character\'s own picture, keyed on its screen, then joined into a sheet', async () => {
  const log: string[] = [], updates: Array<[string, string[]]> = []
  const def = animationDef('walk')!
  const result = await makeAnimation({
    workspace: 'w', kit: kit(), def, model: 'qwen_image_21', signal: new AbortController().signal,
    onUpdate: (takes, stage) => updates.push([stage, takes.map(take => take.status)]),
  }, deps(log))
  const generated = log.filter(line => line.startsWith('generate'))
  assert.equal(generated.length, 4)
  for (const [index, pose] of def.poses.entries()) {
    assert.match(generated[index], new RegExp(`prompt-${pose.id} qwen_image_21 neg ${100 + index} \\["/api/v1/file/ana.png\\?workspace=w"\\] identity 896x1152 3:4`))
  }
  assert.match(log[0], /^prompt walk\/contact paper-cutout a detective in a mustard coat$/, 'the style preset and the look reach the prompt')
  assert.ok(log.findIndex(line => line.startsWith('key')) < log.findIndex(line => line.startsWith('generate') && line.includes('prompt-passing ')), 'a pose is keyed before the next is made')
  assert.ok(log.filter(line => line.startsWith('key')).every(line => / green animation-key-.+-walk-/.test(line)))
  assert.match(log.at(-1)!, /^sheet w ana-walk \/api\/v1\/file\/keyed-prompt-contact\.png/)
  assert.deepEqual(result.frames.map(frame => frame.id), ['contact', 'passing', 'contact-b', 'passing-b'])
  assert.deepEqual([result.sheet.count, result.sheet.columns, result.fps, result.loop, result.facing, result.model], [4, 4, 4, 'loop', 'right', 'qwen_image_21'])
  assert.equal(result.prompt, 'prompt-contact')
  assert.deepEqual(updates[0], ['poses', ['waiting', 'waiting', 'waiting', 'waiting']])
  assert.ok(updates.some(([, statuses]) => statuses.includes('generating')) && updates.some(([, statuses]) => statuses.includes('keying')))
  assert.deepEqual(updates.at(-1), ['sheet', ['ready', 'ready', 'ready', 'ready']])
})

test('poses kept from an earlier run are not made again', async () => {
  const log: string[] = []
  const result = await makeAnimation({
    workspace: 'w', kit: kit(), def: animationDef('walk')!, model: 'qwen_image_21', signal: new AbortController().signal, onUpdate: () => {},
    reuse: { contact: '/api/v1/file/keep-contact.png', 'passing-b': '/api/v1/file/keep-pb.png' },
  }, deps(log))
  assert.equal(log.filter(line => line.startsWith('generate')).length, 2)
  assert.deepEqual(result.frames.map(frame => frame.source), ['/api/v1/file/keep-contact.png', '/api/v1/file/keyed-prompt-passing.png?workspace=w', '/api/v1/file/keyed-prompt-contact-b.png?workspace=w', '/api/v1/file/keep-pb.png'])
})

test('a pose that fails stops the run, stays visible, and the poses already made are kept for the retry', async () => {
  const log: string[] = []
  let last: PoseTake[] = []
  await assert.rejects(makeAnimation({
    workspace: 'w', kit: kit(), def: animationDef('walk')!, model: 'qwen_image_21', signal: new AbortController().signal, onUpdate: takes => { last = takes },
  }, deps(log, { failOn: 'contact-b' })), /out of memory/)
  assert.deepEqual(last.map(take => take.status), ['ready', 'ready', 'failed', 'waiting'])
  assert.equal(last[2].error, 'out of memory')
  assert.equal(log.some(line => line.startsWith('sheet')), false, 'no sheet from half the poses')
  assert.deepEqual(Object.keys(keptPoses(last)), ['contact', 'passing'])
})

test('a character with no persistent picture cannot make poses, and a cancelled run makes nothing more', async () => {
  await assert.rejects(makeAnimation({ workspace: 'w', kit: createCharacterKit('Empty'), def: animationDef('wave')!, model: 'm', signal: new AbortController().signal, onUpdate: () => {} }, deps([])), /no persistent picture/)
  const controller = new AbortController(), log: string[] = []
  const base = deps(log)
  await assert.rejects(makeAnimation({ workspace: 'w', kit: kit(), def: animationDef('walk')!, model: 'm', signal: controller.signal, onUpdate: () => {} },
    { ...base, generate: async (...args: Parameters<typeof base.generate>) => { controller.abort(); return base.generate(...args) } }))
  assert.equal(log.filter(line => line.startsWith('generate')).length, 1)
  assert.equal(log.some(line => line.startsWith('sheet')), false)
})

test('the request names the nearest aspect of the resolution', () => {
  assert.equal(aspectOf('896x1152'), '3:4')
  assert.equal(aspectOf('1024x1024'), '1:1')
  assert.equal(aspectOf('1344x768'), '16:9')
  assert.equal(aspectOf('nonsense'), '1:1')
})
