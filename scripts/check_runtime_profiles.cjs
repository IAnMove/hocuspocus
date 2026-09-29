// Execute launcher plans with mocked Pinokio capabilities; never install packages.
const assert = require('node:assert/strict')
const path = require('node:path')
const vm = require('node:vm')
const runtime = require('../runtime_install')

function render(template, context) {
  return template.replace(/\{\{([\s\S]*?)\}\}/g, (_, expression) => vm.runInNewContext(expression, context))
}

function context(platform) {
  return {platform, path: platform === 'win32' ? path.win32 : path.posix,
    cwd: platform === 'win32' ? 'C:\\Pinokio Apps\\HocusPocus' : '/tmp/other location/hocus',
    which: () => platform === 'win32' ? 'C:\\CUDA\\bin\\nvcc.exe' : '/opt/cuda/bin/nvcc',
    exists: () => true, input: {success: true},
    local: {runtime: {engines: Object.fromEntries(Object.keys(runtime.catalog.engines).map(k => [k, {supported: true, installed: false}]))}},
  }
}

for (const platform of ['linux', 'win32']) {
  const ctx = context(platform)
  const steps = runtime.installEngines(['wangp', 'hunyuan3d', 'minimax_h3'])
    .filter(step => render(step.when, ctx) === 'true')
  for (const step of steps.filter(s => s.method === 'shell.run')) {
    const command = render(step.params.message, ctx)
    assert(command.includes('runtime_failed.py'), 'Every shell failure must propagate')
    if (!step.params.env) continue
    const constraint = render(step.params.env.UV_CONSTRAINT, ctx)
    assert.equal(constraint, ctx.path.resolve(ctx.cwd, `app/runtime/constraints/${platform}-${
      constraint.match(/(?:linux|win32)-(\w+)\.txt$/)[1]}.txt`))
    if (command.includes('runtime_pip.py')) {
      assert(!command.includes("path.resolve('"))
      assert(command.includes(ctx.cwd), 'Package install must select this checkout explicitly')
    }
  }
  const all = JSON.stringify(steps)
  const preflight = runtime.preflight().filter(step => step.method === 'shell.run' &&
    (!step.when || render(step.when, ctx) === 'true'))
  assert.equal(JSON.stringify(preflight).includes('windows_toolchain.py'), platform === 'win32')
  if (platform === 'win32') {
    assert(all.includes('uninstall torchcodec flash-attn'), 'Repair must remove incompatible external attention')
    assert(!all.includes('targets/x86_64-linux'))
    assert(!all.includes('bash compile_mesh_painter'))
    assert(all.includes('build_mesh_painter.py'))
    assert.equal(runtime.python('minimax_h3', platform), 'app/services/minimax_h3/env/python.exe')
  }
}

// Machines without a local AI recipe (AMD, Intel, CPU, old drivers) install core only.
for (const platform of ['linux', 'win32', 'darwin']) {
  const ctx = context(platform)
  const steps = runtime.installEngines(['core', 'wangp']).filter(step => render(step.when, {
    ...ctx, local: {runtime: {engines: {core: {supported: true, installed: false}, wangp: {supported: false}}}},
  }) === 'true')
  const commands = steps.filter(s => s.method === 'shell.run').map(s => render(s.params.message, ctx))
  assert(commands.length, `${platform}: core must install`)
  assert(commands.every(c => c.includes('runtime_failed.py')), 'Every core shell failure must propagate')
  assert(commands.some(c => c.includes(`app/runtime/locks/${platform}-core.txt`)), `${platform}: core lock unused`)
  assert(commands.some(c => c.includes('ffmpeg')), `${platform}: core editors need FFmpeg`)
  assert(!JSON.stringify(steps).match(/torch|\+cu\d|torch\.js|wangp/), `${platform}: core must not install CUDA engines`)
}

// A child aborts with undefined in Pinokio; the parent must stop, not publish success.
const guard = runtime.call('torch.js')[1]
for (const input of [undefined, null, {}, {success: false}]) {
  assert.equal(render(guard.when, {input}), 'true')
  assert.equal(guard.next, null)
}
assert.equal(render(guard.when, {input: {success: true}}), 'false')
for (const filename of ['torch', 'runtime_setup', 'sam_install', 'rigging_install', 'ui_build']) {
  const final = require(`../${filename}.js`).run.at(-1)
  assert.equal(final.method, 'script.return')
  assert.equal(final.params.success, true)
}
assert(!runtime.guarded('some-command').includes('Error:'), 'PTY echo must not trigger an error on success')

// Real host shell, including cmd.exe on Windows CI. A silent failure must
// produce Pinokio's error sentinel and never execute the following command.
const {spawnSync} = require('node:child_process')
const host = {...context(process.platform), path, cwd: path.resolve(__dirname, '..')}
for (const exitCode of [0, 7]) {
  const command = render(runtime.guarded([
    `python -c "import sys; sys.exit(${exitCode})"`,
    'python -c "print(731729)"',
  ]), host)
  const result = spawnSync(command, {shell: true, encoding: 'utf8'})
  assert(!result.error, result.error?.message)
  const output = result.stdout + result.stderr
  assert.equal(output.includes('731729'), exitCode === 0, output)
  assert.equal(output.includes('Error: HOCUS_RUNTIME_FAILED'), exitCode !== 0, output)
}
console.log('Runtime profile launcher execution contract: PASS')

async function checkUiLaunchers() {
  for (const plan of [require('../runtime_setup'), await require('../start')({port: async () => 7860})]) {
    assert.equal(plan.run[0].method, 'script.start')
    assert.equal(plan.run[0].params.uri, 'ui_build.js')
    assert.equal(plan.run[1].next, null, 'A failed UI child must stop setup/start')
  }
  const menu = require('../pinokio').menu
  const flatten = items => items.flatMap(item => [item, ...flatten(item.menu || [])])
  const info = {exists: () => true, running: () => false, local: () => ({})}
  const repair = (await menu({}, info)).find(item => item.href === 'ui_build.js')
  assert.equal(repair.params.force, true)
  const busy = await menu({}, {...info, running: name => name === 'ui_build.js'})
  assert.equal(busy[0].href, 'ui_build.js')
  assert.equal(busy[0].default, true)
  for (const platform of ['win32', 'linux', 'darwin']) {
    const entries = flatten(await menu({platform, arch: 'x64', gpu: 'nvidia'}, info))
    assert.equal(entries.some(item => item.href === 'sam_install.js'), platform !== 'darwin')
    assert.equal(entries.some(item => item.href === 'rigging_install.js'), platform === 'linux')
    assert(entries.some(item => item.href === 'start.js'), 'Existing Start must remain accessible')
  }
  const unknown = flatten(await menu({}, info))
  assert(unknown.some(item => item.href === 'sam_install.js'), 'Unknown hardware must not hide features')
  const pending = flatten(await menu({platform: 'win32', arch: 'unknown', gpu: 'unknown'}, info))
  assert(pending.some(item => item.href === 'sam_install.js'))
  const amd = flatten(await menu({platform: 'linux', gpu: 'amd'}, info))
  assert(!amd.some(item => item.href === 'rigging_install.js'))
  // A core install hides WanGP-only entries and CUDA installers, even before GPU inventory loads.
  const coreInfo = {...info, exists: name => name !== 'app/.runtime/wangp.managed'}
  const core = flatten(await menu({}, coreInfo))
  assert(core.some(item => item.href === 'start.js' && !item.params), 'Core must keep Start')
  assert(!core.some(item => item.text === 'LoRAs' || item.params?.compile), 'Core has no WanGP models')
  assert(!core.some(item => ['sam_install.js', 'rigging_install.js'].includes(item.href)))
  console.log('React repair/start/menu contract: PASS')
}
checkUiLaunchers().catch(error => { console.error(error); process.exitCode = 1 })
