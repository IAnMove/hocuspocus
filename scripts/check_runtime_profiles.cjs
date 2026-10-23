// Execute launcher plans with mocked Pinokio capabilities; never install packages.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const runtime = require('../runtime_install')

assert.equal(require('../trellis2_install').requires.bundle, 'ai')
assert.equal(runtime.catalog.engines.trellis2.defaultInstall, false)
assert.deepEqual(runtime.catalog.engines.trellis2.platforms, ['linux'])
assert.equal(runtime.catalog.engines.trellis2.env, 'app/services/model3d_runtimes/trellis2/env')
const trellisPlan = JSON.stringify(runtime.installEngines(['trellis2']))
assert(trellisPlan.includes('install_native.py') && trellisPlan.includes('cuda-toolkit=12.4'))
assert(trellisPlan.includes('git submodule update --init --recursive'))
assert(!trellisPlan.includes('services/trellis2/assets.py'), 'Runtime setup must never download model weights')

function render(template, context) {
  return template.replace(/\{\{([\s\S]*?)\}\}/g, (_, expression) => vm.runInNewContext(expression, context))
}

// A template that is one single expression keeps its type (Pinokio does the same), so a computed form stays a list.
function evaluate(template, context) {
  const single = template.match(/^\{\{([\s\S]*)\}\}$/)
  if (!single) return render(template, context)
  const value = vm.runInNewContext(single[1], context)
  // Objects built inside the vm have another Array/Object realm; copy them so deepEqual compares plain values.
  return typeof value === 'object' && value !== null ? JSON.parse(JSON.stringify(value)) : value
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
  // Only the optional Hunyuan3D installer needs the Windows compiler; Install never asks for it.
  const toolchain = engine => JSON.stringify(runtime.preflight(engine).filter(step => step.method === 'shell.run' &&
    (!step.when || render(step.when, ctx) === 'true'))).includes('windows_toolchain.py')
  assert.equal(toolchain('hunyuan3d'), platform === 'win32')
  assert(!toolchain() && !toolchain('sam'), 'Main Install must not require Visual Studio')
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
  const ctx = {...context(platform), which: name => name === 'ffmpeg' ? null : '/usr/bin/' + name}
  const coreOnly = {runtime: {engines: {core: {supported: true, installed: false}, wangp: {supported: false}}}}
  const steps = runtime.installEngines(['core', 'wangp']).filter(step => render(step.when, {
    ...ctx, local: coreOnly,
  }) === 'true')
  // Pinokio pins FFmpeg in its shared base; core installs it only when it is missing.
  const withFfmpeg = runtime.installEngines(['core']).filter(step => render(step.when, {
    ...ctx, which: name => '/usr/bin/' + name, local: coreOnly,
  }) === 'true')
  assert(!JSON.stringify(withFfmpeg).includes('conda install'), `${platform}: shared FFmpeg must not be replaced`)
  const commands = steps.filter(s => s.method === 'shell.run').map(s => render(s.params.message, ctx))
  assert(commands.length, `${platform}: core must install`)
  assert(commands.every(c => c.includes('runtime_failed.py')), 'Every core shell failure must propagate')
  assert(commands.some(c => c.includes(`app/runtime/locks/${platform}-core.txt`)), `${platform}: core lock unused`)
  assert(commands.some(c => c.includes('ffmpeg')), `${platform}: core editors need FFmpeg`)
  assert(!JSON.stringify(steps).match(/torch|\+cu\d|torch\.js|wangp/), `${platform}: core must not install CUDA engines`)
}

// Hub login keeps its code, link and outcome in the terminal, and core skips it.
const login = require('../install').run.filter(step => JSON.stringify(step).includes('HuggingFace') || step.method === 'hf.login')
const hf = login.find(step => step.method === 'hf.login')
assert.equal(hf.params.modal, false, 'A modal closes before the device code is entered')
assert.notEqual(hf.params.wait, false, 'Install must report whether login finished')
for (const step of login) {
  assert.equal(render(step.when, {local: {runtime: {engines: {wangp: {supported: false}}}}}), 'false')
}
assert.equal(require('../hf_login').run.at(-1).params.success, true)

// A child aborts with undefined in Pinokio; the parent must stop, not publish success.
const guard = runtime.call('torch.js')[1]
for (const input of [undefined, null, {}, {success: false}]) {
  assert.equal(render(guard.when, {input}), 'true')
  assert.equal(guard.next, null)
}
assert.equal(render(guard.when, {input: {success: true}}), 'false')
for (const filename of ['torch', 'runtime_setup', 'hunyuan3d_install', 'sam_install', 'rigging_install', 'minimax_h3_install', 'ui_build', 'hf_login']) {
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
// Optional components come from app/runtime/install_catalog.json: Install asks what to add,
// Update only refreshes what is already there, and the base install never includes them.
const components = require('../install_components')
const catalogIds = require('../app/runtime/install_catalog.json').components.map(c => c.id)
const catalogEngines = require('../app/runtime/install_catalog.json').components.map(c => c.engine)
assert.deepEqual(components.components.map(c => c.id), catalogIds)
for (const component of components.components) {
  assert(runtime.catalog.engines[component.engine], `${component.id}: engine missing from profiles.json`)
  assert(fs.existsSync(path.resolve(__dirname, '..', component.script)), `${component.id}: missing ${component.script}`)
  assert.equal(require(`../${component.script}`).run.at(-1).method, 'script.return')
}
const setupPlan = require('../runtime_setup').run
assert(!JSON.stringify(setupPlan).includes('engines.minimax_h3.installed'), 'H3 Legacy must not be part of the base install')
const optionalStep = id => components.setupSteps().find(step => step.params?.uri === `${id}_install.js`)
const setupContext = (args, present = [], unsupported = []) => ({
  ...context('linux'), args, exists: name => present.includes(name),
  local: {runtime: {engines: Object.fromEntries(Object.keys(runtime.catalog.engines).map(
    k => [k, {supported: !unsupported.includes(k), installed: false}]))}},
})
const runsSetup = (args, present, unsupported) => components.components
  .filter(c => render(optionalStep(c.id).when, setupContext(args, present, unsupported)) === 'true').map(c => c.id)
assert.deepEqual(runsSetup({update: true}), [], 'Update must not add components nobody installed')
assert.deepEqual(runsSetup({update: false}), [], 'Install without ticks adds nothing')
assert.deepEqual(runsSetup({update: false, extras: ''}), [])
assert.deepEqual(runsSetup({update: true}, ['app/services/sam/env', 'app/services/minimax_h3/env']), ['sam', 'minimax_h3'],
  'Update keeps refreshing what exists, H3 Legacy included')
assert.deepEqual(runsSetup({update: false, extras: 'rigging,minimax_h3'}), ['rigging', 'minimax_h3'])
assert.deepEqual(runsSetup({update: false, extras: 'sam'}, [], ['sam']), [], 'An unsupported engine is skipped, not failed')
const failure = components.setupSteps().find(step => step.params?.uri === undefined && step.next === null)
assert.equal(render(failure.when, {...setupContext({update: false, extras: 'sam'}), input: {success: false}}), 'false',
  'A component that was not started cannot report a failed install')

const dialog = components.chooseSteps()
const allEngines = Object.fromEntries(Object.keys(runtime.catalog.engines).map(name => [name, {supported: true, installed: false}]))
const machine = (patch = {}) => ({local: {runtime: {engines: Object.fromEntries(
  Object.entries(allEngines).map(([name, state]) => [name, {...state, ...(patch[name] || {})}]))}}})
const offeredKeys = patch => evaluate(dialog.find(step => step.method === 'input').params.form, machine(patch)).map(field => field.key)
const form = evaluate(dialog.find(step => step.method === 'input').params.form, machine())
assert.deepEqual(form.map(field => field.key), catalogIds)
assert(form.every(field => field.type === 'checkbox' && field.title.includes('GB') && field.description))
assert.deepEqual(offeredKeys({rigging: {supported: false}, trellis2: {supported: false}}),
  catalogIds.filter(id => !['rigging', 'trellis2'].includes(id)), 'Extras this computer cannot run are not offered')
assert.deepEqual(offeredKeys({sam: {installed: true}}), catalogIds.filter(id => id !== 'sam'), 'Installed extras are not offered again')
assert(dialog[0].params.description.includes('always installed'))
assert.equal(dialog[0].params.confirm, 'Install', 'The dialog has one button and it must say what it does')
const choice = input => render(dialog[1].params.extras, {input})
assert.equal(choice({sam: true, rigging: false, minimax_h3: true}), 'sam,minimax_h3')
assert.equal(choice({}), '')
assert.equal(choice(undefined), '')
for (const step of dialog) {
  assert.equal(render(step.when, machine({wangp: {supported: false}})), 'false', 'Core machines are not asked')
  assert.equal(render(step.when, machine()), 'true')
  const everything = Object.fromEntries(catalogEngines.map(name => [name, {installed: true}]))
  assert.equal(render(step.when, machine(everything)), 'false', 'With every extra installed there is nothing to ask')
  const nothingRuns = Object.fromEntries(catalogEngines.map(name => [name, {supported: false}]))
  assert.equal(render(step.when, machine(nothingRuns)), 'false', 'With no extra this computer can run there is nothing to ask')
}
const description = dialog[0].params.description
assert(render(description, {local: {runtime: {diskFreeGiB: 106, unavailable: ['Not available here: UniRig. Linux only.']}}}).includes('Not available here: UniRig'))
assert(!render(description, {local: {runtime: {diskFreeGiB: 106, unavailable: []}}}).includes('Optional, from the Advanced menu'),
  'The dialog lists the extras itself; it must not repeat them')
const finalDialog = require('../install').run.filter(step => step.method === 'input').pop().params.description
assert(render(finalDialog, machine()).includes('Settings > Installation'), 'Computers with extras are told where to manage them')
assert(!render(finalDialog, machine({wangp: {supported: false}})).includes('Settings > Installation'), 'Core-only computers have no extras to manage')
const handoff = require('../install').run.find(step => step.params?.uri === 'runtime_setup.js').params.params
assert.equal(handoff.update, false)
assert.equal(render(handoff.extras, {local: {extras: 'sam,rigging'}}), 'sam,rigging')
assert.equal(render(handoff.extras, {local: {}}), '', 'A skipped dialog hands over no extras')
assert.deepEqual(require('../install').run.map(step => step.method).filter(m => m === 'input').length, 2)

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
  for (const platform of ['win32', 'linux', 'darwin']) {
    const items = flatten(await menu({platform, arch: 'x64', gpu: 'nvidia'}, info))
    assert.equal(items.some(item => item.href === 'minimax_h3_install.js'), platform !== 'darwin')
    assert.equal(items.find(item => item.href === 'creation_models_install.js').text, 'Update FLUX 3 / Drama 3 Support')
  }
  const fresh = flatten(await menu({platform: 'linux', arch: 'x64', gpu: 'nvidia'}, {...info, exists: name => name === 'app/env'}))
  assert.equal(fresh.find(item => item.href === 'minimax_h3_install.js').text, 'Install MiniMax H3 Legacy (ComfyUI)')
  assert(fresh.some(item => item.href === 'creation_models_install.js'), 'FLUX 3 / Drama 3 stays on every computer')
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
  assert(!core.some(item => ['hunyuan3d_install.js', 'sam_install.js', 'rigging_install.js', 'minimax_h3_install.js', 'hf_login.js'].includes(item.href)))
  const nvidia = flatten(await menu({platform: 'win32', arch: 'x64', gpu: 'nvidia'}, info))
  assert(!nvidia.some(item => item.href === 'trellis2_install.js'), 'Official TRELLIS recipe is Linux-only')
  const linux = flatten(await menu({platform: 'linux', arch: 'x64', gpu: 'nvidia'}, info))
  assert(linux.some(item => item.href === 'trellis2_install.js'), 'TRELLIS must be installable on demand')
  assert(nvidia.some(item => item.href === 'hunyuan3d_install.js'), '3D generation must be installable on demand')
  // Setup installs only default engines; Hunyuan3D is refreshed only where it is present.
  const setupPlan = JSON.stringify(require('../runtime_setup').run)
  assert(setupPlan.includes("exists('app/services/hunyuan3d/env')"))
  assert(!runtime.installEngines(['core', 'wangp', 'minimax_h3']).some(step => JSON.stringify(step).includes('hunyuan3d/env')))
  assert(flatten(await menu({}, info)).some(item => item.href === 'hf_login.js'), 'Login must be retryable')
  console.log('React repair/start/menu contract: PASS')
}
checkUiLaunchers().catch(error => { console.error(error); process.exitCode = 1 })
