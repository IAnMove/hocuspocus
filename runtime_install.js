// One recipe builder for Install, Update and optional engines.
// Pattern: Pinokio system/examples/comfy/install.js shell.run + script.start.
//
// This file is not hashed into the install fingerprint. When the steps for an
// engine change, bump installStepsVersion on that engine in
// app/runtime/profiles.json. Windows-only steps bump windows.installStepsVersion
// so Linux receipts stay valid. See docs/development/RUNTIME_PROFILES.md.
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
  if (args.startsWith('uninstall ')) {
    const packages = new Set([...args.slice(10).split(' '), ...(selected(engine, platform).excludedPackages || [])])
    args = `uninstall ${[...packages].join(' ')}`
  }
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
    // Fail before lengthy downloads if Windows cannot compile the requested 3D engine.
    ...(engine !== 'hunyuan3d' ? [] : [{
      when: "{{platform === 'win32' && local.runtime.engines.hunyuan3d.supported && !local.runtime.engines.hunyuan3d.installed}}",
      method: 'shell.run', params: {
        message: guarded('python scripts/windows_toolchain.py --cuda 12.8'),
      },
    }]),
  ]
}

// Optional Hub login for local model downloads. Pinokio's modal closes as soon
// as the browser opens unless the step waits, and it prints the device code
// only without a modal, so the code, link and outcome stay in this terminal.
function hfLogin(when) {
  const gate = when ? {when} : {}
  const outcome = "input && input.status === 'success' ? " +
    "'[HuggingFace] ' + (input.already_logged_in ? 'Already logged in.' : 'Logged in.') : " +
    "'[HuggingFace] Not logged in (' + String((input && (input.error || input.status)) || 'no response').replace(/\\.$/, '') + '). " +
    "Optional: public models still download. Retry from Advanced > Log in to Hugging Face.'"
  return [
    {...gate, method: 'log', params: {raw: '[HuggingFace] Optional login lifts download rate limits. ' +
      'The browser opens with the code below; this continues automatically after 3 minutes.'}},
    {...gate, method: 'hf.login', params: {modal: false, timeout: 180000}},
    {...gate, method: 'log', params: {raw: `{{${outcome}}}`}},
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
      // Restore only our exact patch; preserve user/vendor modifications.
      ...(id === 'hunyuan3d21' ? [
        `python "{{path.resolve(cwd, 'app/services/hunyuan3d/patch_windows_sources.py')}}" --restore`,
      ] : []),
      `git fetch --depth 1 origin ${vendor.revision}`, `git checkout --detach ${vendor.revision}`,
      ...(vendor.recursive ? ['git submodule update --init --recursive'] : []),
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
  const torchNames = ['torch', 'torchvision', 'torchaudio'].filter(k => spec[k])
  // CPU wheels: Linux and Windows publish 2.7.0+cpu; macOS publishes 2.7.0 with no local tag.
  // CUDA engines keep the +cu suffix exactly as before.
  const torch = spec.torchIndex === 'cpu'
    ? torchNames.map(k => `${k}==${spec[k]}${platform === 'darwin' ? '' : '+cpu'}`).join(' ') +
      ' --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match'
    : torchNames.map(k => `${k}==${spec[k]}+cu${spec.cuda.replace('.', '')}`).join(' ')
  const removals = engine === 'wangp' && platform === 'win32'
    ? [pip(engine, platform, 'uninstall torchcodec')] : []
  if (engine === 'trellis2') run.push({method: 'shell.run', params: {
    ...shell(engine, platform),
    message: 'conda install -y -c nvidia/label/cuda-12.4.1 -c conda-forge cuda-toolkit=12.4 gcc_linux-64=12 gxx_linux-64=12 make',
  }})
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
  // Pinokio's bundle pins FFmpeg in its shared conda base; never replace that copy.
  if (engine === 'core') run.push({when: "{{!which('ffmpeg')}}", method: 'shell.run', params: {
    message: guarded('conda install -y -c conda-forge ffmpeg'),
  }})
  if (engine === 'wangp') run.push(...call('torch.js', {managed: true}))
  if (engine === 'trellis2') run.push({method: 'shell.run', params: {
    ...shell(engine, platform),
    env: {...shell(engine, platform).env, MAX_JOBS: '2'},
    message: 'python app/services/trellis2/install_native.py',
  }})
  if (engine === 'hunyuan3d') {
    // Windows builds load the CUDA-compatible MSVC toolset chosen by the probe
    // (runtime_profiles.find_msvc); DISTUTILS_USE_SDK makes setuptools use it
    // instead of its own vswhere lookup. Conda's CUDA keeps cudart.lib in
    // Library/lib, not the lib/x64 torch passes to the linker, so it goes on
    // LIB (vcvars64.bat keeps an existing LIB).
    const msvc = platform === 'win32'
      ? m => `{{local.runtime.msvc ? 'call "' + local.runtime.msvc.vcvars + '" -vcvars_ver=' + local.runtime.msvc.toolset + ' >nul && ' : ''}}${m}`
      : m => m
    const msvcEnv = platform === 'win32'
      ? {DISTUTILS_USE_SDK: '1', LIB: "{{path.resolve(path.dirname(which('nvcc')), '../lib')}}"} : {}
    const base = shell(engine, platform)
    run.push({method: 'shell.run', params: {...base, env: {...base.env, ...msvcEnv},
      message: msvc(pip(engine, platform, 'install --no-build-isolation diso==0.1.4'))}})
    if (platform === 'win32') run.push({method: 'shell.run', params: {...base,
      message: 'python app/services/hunyuan3d/patch_windows_sources.py'}})
    run.push(...hunyuanNative.nativeBuildSteps().filter(s => !s.when || s.when.includes(`'${platform}'`)).map(s => {
      const params = shell(engine, platform, s.params.path, {...s.params.env, ...msvcEnv})
      return {...s, params: {...s.params, ...params,
        message: msvc(s.params.message.startsWith('uv pip ') ? pip(engine, platform, s.params.message.slice(7), s.params.path) : s.params.message)},
      }
    }))
    run.push({when: "{{!exists('app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth')}}",
      method: 'fs.download', params: {
        url: 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
        path: 'app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth',
      }})
  }
  if (engine === 'sam') run.push({method: 'shell.run', params: {...shell(engine, platform),
    message: pip(engine, platform, `install ${vendors.sam3.path}`)}})
  if (engine === 'anime_face') run.push({method: 'shell.run', params: {
    ...shell(engine, platform),
    env: {...shell(engine, platform).env, CUDA_VISIBLE_DEVICES: '',
      HF_HOME: 'app/services/anime_face/cache',
      HUGGINGFACE_HUB_CACHE: 'app/services/anime_face/cache/hub'},
    message: 'python -c "from anime_face_detector import create_detector; create_detector(\'yolov3\', device=\'cpu\')"',
  }})
  if (engine === 'rigging') run.push({method: 'shell.run', params: {
    ...shell(engine, platform, '.', {CUDA_HOME: "{{path.resolve(path.dirname(which('nvcc')), '..')}}"}),
    message: [pip(engine, platform, 'install flash-attn==2.7.4.post1 --no-build-isolation'),
      pip(engine, platform, 'install spconv-cu126==2.3.8'),
      pip(engine, platform, 'install torch_scatter==2.1.2 torch_cluster==1.6.3 -f https://data.pyg.org/whl/torch-2.7.0%2Bcu128.html')],
  }})
  if (engine === 'see_through') {
    // Pinned here, not in vendors.json: that file is hashed into every engine's fingerprint.
    const src = spec.source
    const dest = 'app/services/see_through/vendor/see-through'
    const base = shell(engine, platform)
    run.push({when: `{{!exists('${dest}/.git')}}`, method: 'shell.run', params: {
      message: `git clone --depth 1 --no-checkout ${src.url} ${dest}`,
    }})
    run.push({method: 'shell.run', params: {
      path: dest,
      message: `git fetch --depth 1 origin ${src.revision} && git checkout --detach ${src.revision}`,
    }})
    run.push({method: 'shell.run', params: {...base, message: pip(engine, platform, `install -e ${dest}/common`)}})
    run.push({method: 'shell.run', params: {...base, env: {...base.env,
      HF_HOME: "{{path.resolve('app/services/see_through/hf')}}", HF_HUB_DISABLE_TELEMETRY: '1'},
      message: [
        'python -c "from huggingface_hub import snapshot_download; snapshot_download(\'24yearsold/seethroughv0.0.2_layerdiff3d_nf4\')"',
        'python -c "from huggingface_hub import snapshot_download; snapshot_download(\'24yearsold/seethroughv0.0.1_marigold_nf4\')"',
      ]}})
  }
  if (engine === 'mia') run.push({method: 'shell.run', params: {
    ...shell(engine, platform),
    message: [
      pip(engine, platform, 'install pytorch3d==0.7.7+pt2.1.2cu121 --extra-index-url https://miropsota.github.io/torch_packages_builder'),
      pip(engine, platform, 'install torch-cluster -f https://data.pyg.org/whl/torch-2.1.2+cu121.html'),
      'app/services/mia/env/bin/python app/services/mia/fetch_weights.py',
    ],
  }})
  // Corrects the few upstream wheel tags uv's check rejects (decord on Linux). It is a no-op
  // elsewhere and is not hashed: existing installs never needed it, so they stay current.
  run.push({method: 'shell.run', params: {...shell(engine, platform), message: [
    'python scripts/runtime_wheel_tags.py',
    pip(engine, platform, 'check'),
    `python scripts/runtime_verify.py --engine ${engine}`,
  ]}})
  // Legacy service markers remain readable; write only after actual verification.
  for (const id of spec.vendors || []) {
    const v = vendors[id]
    run.push({method: 'fs.write', params: {path: v.marker, text: `repository=${v.url}\nrevision=${v.revision}\n`}})
  }
  const markers = {hunyuan3d: '.maestro_hunyuan3d_v1.installed', minimax_h3: '.maestro_minimax_h3_v2.installed', rigging: '.maestro_rigging_v1.installed', mia: '.maestro_mia_v1.installed'}
  if (markers[engine]) run.push({method: 'fs.write', params: {path: `${spec.env}/${markers[engine]}`, text: catalog.revision}})
  if (engine === 'see_through') run.push({method: 'fs.write', params: {
    path: `${spec.env}/.maestro_see_through_v1.installed`, text: spec.source.revision,
  }})
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

module.exports = {catalog, selected, shell, python, pip, guarded, call, preflight, hfLogin, startGuard, startGuards, vendorSteps, installEngines}
