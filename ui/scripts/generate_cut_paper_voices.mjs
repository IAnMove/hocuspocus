#!/usr/bin/env node
/** Generate Tijeral example lines with local Qwen3 CustomVoice. Requires the model installed. */
import { writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const api = process.env.HOCUSPOCUS_API || 'http://127.0.0.1:42006'
const dest = join(root, 'public/examples/cut-paper/voices')
const lines = [
  ['nilo', 'dylan', 'vo-nilo-nilo-1.wav', 'La fuente no está congelada. Alguien le pegó un cuadrado de papel cebolla.', 12],
  ['berta', 'serena', 'vo-berta-berta-1.wav', 'Pues sabe a hielo. Lo probé.', 8],
  ['nilo', 'dylan', 'vo-nilo-nilo-2.wav', 'Berta, eso es cola.', 6],
  ['berta', 'serena', 'vo-berta-berta-2.wav', 'Cola fría. Como hielo.', 8],
  ['kito', 'sohee', 'vo-kito-kito-1.wav', '¡Era un sticker!', 6],
]

async function wait(ms) { await new Promise(resolve => setTimeout(resolve, ms)) }

for (const [who, voiceId, filename, prompt, duration] of lines) {
  const submitted = await fetch(`${api}/api/v1/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model_type: 'qwen3_tts_customvoice',
      generation_mode: 'audio',
      prompt,
      video_length: 0,
      image_mode: 0,
      multi_prompts_gen_type: 2,
      duration_seconds: duration,
      _audio_sub_mode: 'speech',
      workspace: process.env.HOCUSPOCUS_WORKSPACE || 'default',
      model_mode: voiceId,
    }),
  })
  if (!submitted.ok) throw new Error(`${who} submit HTTP ${submitted.status}: ${await submitted.text()}`)
  const { job_id: jobId } = await submitted.json()
  console.log('queued', filename, jobId)
  const deadline = Date.now() + 20 * 60_000
  let status
  while (Date.now() < deadline) {
    const res = await fetch(`${api}/api/v1/status/${encodeURIComponent(jobId)}`)
    if (!res.ok) throw new Error(`${filename} status HTTP ${res.status}`)
    status = await res.json()
    if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') break
    await wait(2000)
  }
  if (status?.status !== 'completed') throw new Error(`${filename} ${status?.status}: ${status?.error || status?.message || 'timeout'}`)
  const file = (status.output_files || []).find(name => /\.(wav|mp3|m4a)$/i.test(name))
  if (!file) throw new Error(`${filename} completed without audio`)
  const audio = await fetch(`${api}/api/v1/file/${encodeURIComponent(file.split(/[\\/]/).pop())}`)
  if (!audio.ok) throw new Error(`${filename} download HTTP ${audio.status}`)
  await writeFile(join(dest, filename), Buffer.from(await audio.arrayBuffer()))
  console.log('wrote', filename)
}
console.log('done')
