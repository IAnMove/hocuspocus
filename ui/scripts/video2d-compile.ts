import { readFileSync } from 'node:fs'
import { compilePayload } from './video2dCompile.ts'

function runningAsCli() {
  return process.argv.some(arg => arg.endsWith('video2d-compile.ts'))
}

if (runningAsCli()) {
  const payload = JSON.parse(readFileSync(0, 'utf8')) as unknown
  process.stdout.write(`${JSON.stringify(compilePayload(payload))}\n`)
}
