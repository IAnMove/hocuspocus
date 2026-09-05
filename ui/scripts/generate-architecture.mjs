/** Build-only bridge: no backend imports, models, network or server endpoints. */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../', import.meta.url))
const python = process.env.HOCUSPOCUS_GRAPH_PYTHON
  || (process.platform === 'win32' ? 'python' : 'python3')
const result = spawnSync(python, [
  'scripts/graphs/story_director_audio_flow.py',
  '--output', 'ui/public/dev/architecture/story-director-audio.json',
], { cwd: root, stdio: 'inherit', timeout: 60_000 })

if (result.error) {
  console.error('Architecture snapshot generation failed:', result.error.message)
  console.error('Install Python 3.10+ or set HOCUSPOCUS_GRAPH_PYTHON to its executable path.')
}
process.exitCode = result.status ?? 1
