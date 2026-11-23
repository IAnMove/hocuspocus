import JSZip from 'jszip'
import { createWorkspace, fetchDefaults, fetchJobStatus, getFileUrl, uploadImage } from '../../api/client'
import { createStudioImageGenerationCommand, submitImageGenerationCommand } from '../../api/imageGenerationCommands'

const labels = ['Picture 1', 'Picture 2']
const csvField = /(?:"((?:[^"]|"")*)"|([^",\r\n]*))(,|\r?\n|$)/gy

export function parseBatchCsv(csv: string): string[][] {
  const records: string[][] = []
  let row: string[] = []
  let offset = csv.startsWith('\uFEFF') ? 1 : 0
  while (offset < csv.length || row.length) {
    csvField.lastIndex = offset
    const match = csvField.exec(csv)
    if (!match) throw new Error('CSV inválido')
    row.push(match[1]?.replaceAll('""', '"') ?? match[2])
    offset = csvField.lastIndex
    if (match[3] === ',') continue
    if (row.some(Boolean)) records.push(row)
    row = []
  }
  return records
}

type Row = { id: string; prompt: string; references: string[]; seed: number; output?: string; error?: string; jobId?: string }

const escapeHtml = (value: string) => value.replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[char]!)

export async function runBatch(file: File, progress: (status: string) => void) {
  const zip = await JSZip.loadAsync(await file.arrayBuffer())
  const manifest = zip.file('lote.json')
  const csv = zip.file('prompts.csv')
  if (!manifest || !csv) throw new Error('El ZIP requiere lote.json y prompts.csv')
  const config = JSON.parse(await manifest.async('string'))
  if (typeof config.workspace !== 'string' || !/^[\w][\w-]*$/.test(config.workspace)
    || typeof config.model !== 'string' || !config.model || typeof config.resolution !== 'string'
    || !/^\d+x\d+$/.test(config.resolution)) throw new Error('Configuración del lote inválida')

  const [header, ...records] = parseBatchCsv(await csv.async('string'))
  if (header?.join(',') !== 'id,prompt,references,seed' || !records.length) throw new Error('Cabecera CSV inválida o lote vacío')
  const seen = new Set<string>()
  const rows: Row[] = records.map(([id, prompt, refs, rawSeed, ...extra], index) => {
    const references = refs?.split('|') ?? []
    const seed = Number(rawSeed)
    if (!id || !/^[a-z0-9_-]+$/i.test(id) || seen.has(id.toLowerCase()) || !prompt?.trim()
      || !/^-?\d+$/.test(rawSeed) || !Number.isSafeInteger(seed) || extra.length
      || !references.length || new Set(references).size !== references.length
      || references.some(key => !labels.includes(key))) throw new Error(`Fila CSV inválida: ${index + 2}`)
    seen.add(id.toLowerCase())
    return { id, prompt, references, seed }
  })
  const refs = new Map<string, { path: string; file: File; url?: string }>()
  for (const key of new Set(rows.flatMap(row => row.references))) {
    const path = config.references?.[key]
    const match = typeof path === 'string' && /^referencias\/[^/\\]+\.(png|jpe?g|webp)$/i.exec(path)
    const entry = match && zip.file(path)
    if (!entry) throw new Error(`Falta el archivo de ${key}`)
    const extension = match[1].toLowerCase()
    refs.set(key, { path, file: new File([await entry.async('blob')], path.split('/').pop()!, {
      type: `image/${extension === 'jpg' ? 'jpeg' : extension}`,
    }) })
  }

  const defaults = await fetchDefaults(config.model)
  const tuning = config.model === 'qwen_image_21_viggle_turbo'
    ? { num_inference_steps: 6, guidance_scale: 1 }
    : { num_inference_steps: defaults.num_inference_steps, guidance_scale: defaults.guidance_scale }
  await createWorkspace(config.workspace)
  const result = new JSZip()
  for (const ref of refs.values()) {
    result.file(ref.path, await ref.file.arrayBuffer())
    ref.url = (await uploadImage(ref.file)).url
  }
  const batchId = crypto.randomUUID()
  for (const [index, row] of rows.entries()) {
    progress(`${index + 1} / ${rows.length} · ${row.id}`)
    try {
      const command = createStudioImageGenerationCommand({
        workspace: config.workspace, model_type: config.model, resolution: config.resolution,
        prompt: row.prompt, seed: row.seed, batch_size: 1, prompt_enhancer: '',
        video_prompt_type: 'I', image_refs: row.references.map(key => refs.get(key)!.url),
        ...tuning,
      }, `batch-${batchId}-${index}`)
      row.jobId = (await submitImageGenerationCommand(command)).result.job_id
      for (;;) {
        const job = await fetchJobStatus(row.jobId)
        if (job.status === 'completed') {
          const name = job.output_files[0]
          const extension = name?.match(/\.(png|jpe?g|webp)$/i)?.[0]
          if (!extension) throw new Error('El trabajo no devolvió una imagen')
          const response = await fetch(getFileUrl(name, config.workspace))
          if (!response.ok) throw new Error(`Descarga fallida (HTTP ${response.status})`)
          const image = await response.blob()
          if (!image.size || !image.type.startsWith('image/')) throw new Error('Archivo de imagen inválido')
          row.output = `imagenes/${row.id}${extension}`
          result.file(row.output, await image.arrayBuffer())
          break
        }
        if (['failed', 'cancelled', 'leftover', 'interrupted'].includes(job.status)) {
          throw new Error(job.error || job.status)
        }
        await new Promise(resolve => setTimeout(resolve, 2000))
      }
    } catch (error) {
      row.error = error instanceof Error ? error.message : String(error)
    }
  }
  const csvValue = (value: string | number | undefined) => '"' + String(value ?? '').replaceAll('"', '""') + '"'
  const report = rows.map(row => [row.id, row.prompt, row.references.join('|'), row.seed, row.output, row.error]
    .map(csvValue).join(','))
  result.file('resultados.csv', ['id,prompt,references,seed,output,error', ...report].join('\r\n'))
  result.file('manifest.json', JSON.stringify({ workspace: config.workspace, model: config.model, rows }, null, 2))
  const table = rows.map(row => `<tr><td>${row.id}</td><td>${escapeHtml(row.prompt)}</td><td>${row.references.map(key => {
    const path = escapeHtml(encodeURI(refs.get(key)!.path))
    return `<img src="${path}" alt="${key}">`
  }).join(' ')}</td><td>${row.output
    ? `<a href="${row.output}"><img src="${row.output}" alt="${row.id}"></a>`
    : escapeHtml(row.error ?? '')}</td></tr>`).join('')
  result.file('index.html', `<!doctype html><meta charset="utf-8"><title>Resultados</title>
<style>table{border-collapse:collapse}td,th{padding:.5rem;border:1px solid #999;white-space:pre-wrap}img{max-width:180px;max-height:180px}</style>
<table><thead><tr><th>ID</th><th>Prompt</th><th>Referencias</th><th>Resultado</th></tr></thead><tbody>${table}</tbody></table>`)
  return { archive: await result.generateAsync({ type: 'blob' }), done: rows.filter(row => row.output).length, total: rows.length }
}
