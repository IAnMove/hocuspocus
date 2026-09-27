// One recipe builder for Install, Update and optional engines.
// Pattern: Pinokio system/examples/comfy/install.js shell.run + script.start.
const path = require('node:path')
const catalog = require('./app/runtime/profiles.json')
const vendors = require('./vendor_revisions')
const hunyuanNative = require('./hunyuan_native')

function selected(engine, platform) {
  const base = catalog.engines[engine]
  const override = platform === 'win32' ? (base.windows || {}) : {}
  return {...base, ...override, constraints: {...base.constraints, ...override.constraints}}
}

function python(engine, platform) {
  const spec = catalog.engines[engine]
  const suffix = platform === 'win32'
    ? (spec.environment === 'venv' ? 'Scripts/python.exe' : 'python.exe') : 'bin/python'
  return `${spec.env}/${suffix}`
}

function shell(engine, platform, cwd = '.', extraEnv = {}) {
  const spec = selected(engine, platform)
  const relative = p => path.posix.relative(cwd, p) || '.'
  return {
    path: cwd,
    ...(spec.environment === 'venv' ? {venv: relative(spec.env)}
      : {conda: {path: relative(spec.env), python: spec.python}}),
    env: {
      PYTHONNOUSERSITE: '1', PYTHONPATH: '', PYTHONHOME: '',
      UV_CONSTRAINT: `{{path.resolve(cwd, 'app/runtime/constraints/${platform}-${engine}.txt')}}`,
      UV_BUILD_CONSTRAINT: `{{path.resolve(cwd, 'app/runtime/constraints/${platform}-${engine}.txt')}}`,
      PIP_CONSTRAINT: `{{path.resolve(cwd, 'app/runtime/constraints/${platform}-${engine}.txt')}}`,
      ...extraEnv,
    },
  }
}

function pip(engine, platform, args, cwd = '.') {
  return `python "{{path.resolve(cwd, 'scripts/runtime_pip.py')}}" --engine ${engine} -- ${args}`
}

function guarded(messages) {
  const block = (Array.isArray(messages) ? messages : [messages]).join(' && ')
  return `(${block}) || python "{{path.resolve(cwd, 'scripts/runtime_failed.py')}}"`
}

function call(uri, params = {}) {
  return [
    {method: 'script.start', params: {uri, params}},
    {when: '{{!input || input.success !== true}}', method: 'notify', params: {
      html: 'Runtime setup stopped. See the error in the terminal; installation has not completed.',
    }, next: null},
  ]
}

function preflight(engine = null) {
  const test = engine ? `local.runtime.engines.${engine}.supported` : 'local.runtime.supported'
  return [
    {method: 'shell.run', params: {message: guarded('python scripts/runtime_probe.py --platform "{{platform}}" --arch "{{arch}}" --gpu "{{gpu}}"')}},
    {method: 'fs.read', params: {path: 'app/.runtime/capabilities.json', encoding: 'utf8'}},
    {method: 'local.set', params: {runtime: '{{JSON.parse(input)}}'}},
    {when: '{{!' + test + '}}', method: 'notify', params: {
      html: '{{Object.values(local.runtime.engines).filter(e => !e.supported).map(e => e.reason).join("<br>")}}',
    }, next: null},
  ]
}

function startGuard() {
  return {when: "{{exists('app/.runtime/wangp.managed')}}", method: 'shell.run', params: {
    path: 'app', venv: 'env', env: {PYTHONNOUSERSITE: '1', PYTHONPATH: '', PYTHONHOME: ''},
    message: guarded('python ../scripts/runtime_probe.py --require-installed wangp'),
  }}
}

function startGuards() {
  return [
    startGuard(),
    {when: "{{exists('app/.runtime/core.managed') && !exists('app/.runtime/wangp.managed')}}", method: 'shell.run', params: {
      path: 'app', venv: 'env', env: {PYTHONNOUSERSITE: '1', PYTHONPATH: '', PYTHONHOME: ''},
      message: guarded('python ../scripts/runtime_probe.py --require-installed core'),
    }},
  ]
}

function vendorSteps(id) {
  const vendor = vendors[id]
  if (!vendor) throw new Error(`Unknown vendor ${id}`)
  return [
    {when: `{{!exists('${vendor.path}')}}`, method: 'shell.run', params: {
      message: `git clone --depth 1 --no-checkout ${vendor.url} ${vendor.path}`,
    }},
    {method: 'shell.run', params: {path: vendor.path, message: [
      `git fetch --depth 1 origin ${vendor.revision}`, `git checkout --detach ${vendor.revision}`,
      `python "{{path.resolve(cwd, 'scripts/runtime_vendor.py')}}" ${id}`,
    ]}},
  ]
}

function engineSteps(engine, platform) {
  const spec = selected(engine, platform)
  const run = []
  run.push({method: 'fs.write', params: {path: `app/.runtime/${engine}.managed`, text: catalog.revision}})
  run.push({when: `{{exists('${spec.env}/.hocus-runtime-profile.json')}}`, method: 'fs.rm',
    params: {path: `${spec.env}/.hocus-runtime-profile.json`}})
  for (const id of spec.vendors || []) run.push(...vendorSteps(id))
  if (spec.environment === 'venv') {
    run.push({when: `{{!exists('${spec.env}')}}`, method: 'shell.run', params: {
      message: `uv venv --python ${spec.python} --seed ${spec.env}`,
    }})
  }
  const torch = ['torch', 'torchvision', 'torchaudio'].filter(k => spec[k])
    .map(k => `${k}==${spec[k]}+cu${spec.cuda.replace('.', '')}`).join(' ')
  const removals = engine === 'wangp' && platform === 'win32'
    ? [pip(engine, platform, 'uninstall torchcodec')] : []
  const packages = [
    ...removals,
    ...(torch ? [pip(engine, platform, `install ${torch}`)] : []),
    pip(engine, platform, `install -r app/runtime/locks/${platform}-${engine}.txt`),
  ]
  run.push({method: 'shell.run', params: {...shell(engine, platform), message: packages}})
  const triton = spec.constraints['triton-windows']
  if (platform === 'win32' && triton) run.push({method: 'shell.run', params: {
    ...shell(engine, platform), message: pip(engine, platform, `install triton-windows==${triton}`),
  }})
  if (engine === 'core') run.push({method: 'shell.run', params: {
    message: guarded('conda install -y -c conda-forge ffmpeg'),
  }})
  if (engine === 'wangp') run.push(...call('torch.js', {managed: true}))
  if (engine === 'hunyuan3d') {
    run.push({method: 'shell.run', params: {...shell(engine, platform),
      message: pip(engine, platform, 'install --no-build-isolation diso==0.1.4')}})
    run.push(...hunyuanNative.nativeBuildSteps().filter(s => !s.when || s.when.includes(`'${platform}'`)).map(s => ({
      ...s, params: {...s.params, ...shell(engine, platform, s.params.path, s.params.env),
        message: s.params.message.startsWith('uv pip ') ? pip(engine, platform, s.params.message.slice(7), s.params.path) : s.params.message},
    })))
    run.push({when: "{{!exists('app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth')}}",
      method: 'fs.download', params: {
        url: 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
        path: 'app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth',
      }})
  }
  if (engine === 'sam') run.push({method: 'shell.run', params: {...shell(engine, platform),
    message: pip(engine, platform, `install ${vendors.sam3.path}`)}})
  if (engine === 'rigging') run.push({method: 'shell.run', params: {
    ...shell(engine, platform, '.', {CUDA_HOME: "{{path.resolve(path.dirname(which('nvcc')), '..')}}"}),
    message: [pip(engine, platform, 'install flash-attn==2.7.4.post1 --no-build-isolation'),
      pip(engine, platform, 'install spconv-cu126==2.3.8'),
      pip(engine, platform, 'install torch_scatter==2.1.2 torch_cluster==1.6.3 -f https://data.pyg.org/whl/torch-2.7.0%2Bcu128.html')],
  }})
  run.push({method: 'shell.run', params: {...shell(engine, platform), message: [
    pip(engine, platform, 'check'),
    `python scripts/runtime_verify.py --engine ${engine}`,
  ]}})
  // Legacy service markers remain readable; write only after actual verification.
  for (const id of spec.vendors || []) {
    const v = vendors[id]
    run.push({method: 'fs.write', params: {path: v.marker, text: `repository=${v.url}\nrevision=${v.revision}\n`}})
  }
  const markers = {hunyuan3d: '.maestro_hunyuan3d_v1.installed', minimax_h3: '.maestro_minimax_h3_v2.installed', rigging: '.maestro_rigging_v1.installed'}
  if (markers[engine]) run.push({method: 'fs.write', params: {path: `${spec.env}/${markers[engine]}`, text: catalog.revision}})
  return run.map(step => step.method === 'shell.run' ? {
    ...step, params: {...step.params, message: guarded(step.params.message)},
  } : step)
}

function installEngines(names) {
  return names.flatMap(engine => catalog.engines[engine].platforms.flatMap(platform =>
    engineSteps(engine, platform).map(step => ({...step,
      when: "{{platform === '" + platform + "' && local.runtime.engines." + engine + ".supported && !local.runtime.engines." + engine + ".installed" + (step.when ? " && (" + step.when.slice(2, -2) + ")" : "") + "}}",
    }))))
}

module.exports = {catalog, selected, shell, python, pip, guarded, call, preflight, startGuard, startGuards, vendorSteps, installEngines}
