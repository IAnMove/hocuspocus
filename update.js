const vendors = require("./vendor_revisions")
const hunyuan3d2 = vendors.hunyuan3d2
const hunyuan3d21 = vendors.hunyuan3d21
const sam3 = vendors.sam3
const unirig = vendors.unirig

module.exports = {
  run: [{
    // Never let Update merge around uncommitted work. shell.run returns the
    // porcelain output as input.stdout; the next documented jump either stops
    // with a recoverable message or proceeds to a fast-forward-only pull.
    // The single Maestro repository contains both `ui/` and `app/`, so one
    // clean-tree check protects the complete launcher and application.
    method: "shell.run",
    params: {
      message: "git status --porcelain"
    }
  }, {
    method: "jump",
    params: {
      id: "{{/(?:^|\\r?\\n)[ MADRCU?!]{2} /.test(input.stdout) ? 'dirty' : 'pull'}}"
    }
  }, {
    id: "dirty",
    method: "log",
    params: {
      raw: "Update stopped safely: Maestro has uncommitted changes. Commit or stash them before updating; no files were changed."
    },
    next: null
  }, {
    id: "pull",
    method: "shell.run",
    params: {
      env: {
        LC_ALL: "C"
      },
      message: "git pull --ff-only"
    }
  }, {
    // Branch on the git pull output (captured here as input.stdout — a
    // shell.run always returns its raw terminal content as stdout):
    //   - already current and complete -> jump to "uptodate" and stop
    //   - old install missing native 3D -> jump to "build" for migration
    //   - new commits found             -> jump to "build" for the full update
    // Matches both the modern "Already up to date" and the older git
    // "Already up-to-date" spelling, case-insensitively. If detection
    // ever fails (e.g. empty stdout), the regex simply won't match and
    // we fall through to "build" — the safe default is a full update,
    // never a wrongly-skipped rebuild.
    method: "jump",
    params: {
      id: "{{/(?:fatal:|error:|aborting|no tracking information|specify which branch)/i.test(input.stdout) ? 'pull_failed' : (/already up[- ]to[- ]date/i.test(input.stdout) && exists('app/services/hunyuan3d/env/.maestro_hunyuan3d_v1.installed') && exists('" + hunyuan3d2.marker + "') && exists('" + hunyuan3d21.marker + "') && exists('app/services/hunyuan3d/vendor/Hunyuan3D-2') && exists('app/services/hunyuan3d/vendor/Hunyuan3D-2.1') && ((!exists('app/services/sam/env') && !exists('" + sam3.path + "')) || exists('" + sam3.marker + "')) && ((!exists('app/services/rigging/env') && !exists('" + unirig.path + "')) || (exists('app/services/rigging/env/.maestro_rigging_v1.installed') && exists('" + unirig.marker + "'))) && exists('app/services/minimax_h3/env/.maestro_minimax_h3_v2.installed') && exists('app/services/minimax_h3/vendor/ComfyUI/main.py') && exists('app/postprocessing/seedvc/__init__.py') ? 'uptodate' : 'build')}}"
    }
  }, {
    id: "pull_failed",
    method: "log",
    params: {
      raw: "Update stopped safely because Git could not fast-forward the current branch. Configure its upstream or resolve the Git error shown above; dependencies were not changed."
    },
    next: null
  }, {
    id: "uptodate",
    method: "log",
    params: {
      raw: "Already up to date. Maestro and its bundled runtimes are installed."
    },
    next: null
  }, {
    // Fetch the seed-vc component if missing (GPL-3.0, own repository —
    // see install.js). Runs at the top of the build path so the update
    // that removed the formerly-tracked tree clones it right back, and
    // any later update self-heals a failed clone. Keep the pinned tag in
    // sync with install.js.
    id: "build",
    when: "{{!exists('app/postprocessing/seedvc/__init__.py')}}",
    method: "shell.run",
    params: {
      message: "git clone --depth 1 --branch v1.0.0 https://github.com/Blizaine/maestro-seedvc app/postprocessing/seedvc"
    }
  }, {
    method: "shell.run",
    params: {
      venv: "env",
      path: "app",
      message: "uv pip install -r requirements.txt --index-strategy unsafe-best-match"
    }
  }, {
    // Skip torch.js when the marker file written by torch.js's last
    // successful run is still present — `torch + triton + sage + flash`
    // are already installed at the versions torch.js wants to install.
    // Saves ~60-120s + ~3 GB of redundant downloads on routine updates.
    //
    // When bumping ANY of those package versions inside torch.js, ALSO
    // bump the `_v1` suffix here AND in torch.js's fs.write step. The
    // old marker becomes stale, this `!exists(new_marker)` gate evaluates
    // true on the next update, torch.js runs, and the new marker is
    // written. Old marker stays as harmless cruft until reset.js (which
    // wipes app/env entirely).
    //
    // Recovery path: if torch ever ends up in a broken state (e.g. CPU
    // wheel installed where CUDA is expected) AND the marker is still
    // present, the user can manually delete
    // `app/env/.maestro_torch_v1.installed` and re-run Update to force
    // a full reinstall — or run Reset for a clean slate.
    when: "{{!exists('app/env/.maestro_torch_v1.installed')}}",
    method: "script.start",
    params: {
      uri: "torch.js",
      params: {
        venv: "env",
        path: "app",
        xformers: true
      }
    }
  }, {
    // Mirror of the install.js GGUF-kernels step — idempotent, so
    // re-runs cheaply on every update. Catches existing installs
    // up to the new behavior without forcing a reinstall.
    method: "shell.run",
    params: {
      venv: "env",
      path: "app",
      message: "python scripts/install_gguf_kernels.py"
    }
  }, {
    when: "{{exists('ui/package.json')}}",
    method: "shell.run",
    params: {
      path: "ui",
      message: [
        "npm ci",
        "npm run build"
      ]
    }
  },
  // Update SAM 3.1 service (pull latest + reinstall) ONLY if SAM is
  // already installed. This way:
  //   - Users who never installed SAM (most users) don't get a slow
  //     conda env install they didn't ask for during a regular update.
  //   - Users who DID install SAM keep getting it kept up to date
  //     alongside the main app on every update.
  // Fresh-install path: install.js no longer runs sam_install.js;
  // users who want inpaint click "Install Inpaint Support" from the
  // Pinokio menu, which fires sam_install.js once. After that, this
  // gate is satisfied and SAM updates with every regular update.
  {
    when: "{{exists('app/services/sam/env')}}",
    method: "script.start",
    params: {
      uri: "sam_install.js"
    }
  },
  {
    when: "{{exists('app/services/rigging/env')}}",
    method: "script.start",
    params: {
      uri: "rigging_install.js"
    }
  },
  // Existing installations that predate MiniMax H3 reach this section through
  // the normal build path. The weights remain lazy downloads.
  {
    when: "{{!exists('app/services/minimax_h3/vendor/ComfyUI/main.py')}}",
    method: "shell.run",
    params: {
      message: [
        "git clone --depth 1 --branch minimax_h3 https://github.com/kijai/ComfyUI app/services/minimax_h3/vendor/ComfyUI",
        "git -C app/services/minimax_h3/vendor/ComfyUI fetch --depth 1 origin e2ab36d933356bc8cd6ecb39c655fe8be75af4e5",
        "git -C app/services/minimax_h3/vendor/ComfyUI checkout e2ab36d933356bc8cd6ecb39c655fe8be75af4e5"
      ]
    }
  }, {
    when: "{{exists('app/services/minimax_h3/vendor/ComfyUI/.git')}}",
    method: "shell.run",
    params: {
      path: "app/services/minimax_h3/vendor/ComfyUI",
      message: [
        "git fetch --depth 1 origin e2ab36d933356bc8cd6ecb39c655fe8be75af4e5",
        "git checkout e2ab36d933356bc8cd6ecb39c655fe8be75af4e5"
      ]
    }
  }, {
    method: "shell.run",
    params: {
      conda: { path: "app/services/minimax_h3/env", python: "3.11" },
      message: [
        "uv pip install torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cu130",
        "uv pip install -r app/services/minimax_h3/vendor/ComfyUI/requirements.txt"
      ]
    }
  }, {
    method: "fs.write",
    params: {
      path: "app/services/minimax_h3/env/.maestro_minimax_h3_v2.installed",
      text: "e2ab36d933356bc8cd6ecb39c655fe8be75af4e5 torch-2.10.0-cu130"
    }
  },
  // Existing installations that predate native 3D reach this section through
  // the normal full update path. Model weights remain lazy downloads.
  {
    when: "{{!exists('app/postprocessing/seedvc/__init__.py')}}",
    method: "shell.run",
    params: {
      message: "git clone --depth 1 --branch v1.0.0 https://github.com/Blizaine/maestro-seedvc app/postprocessing/seedvc"
    }
  }, {
    when: "{{!exists('" + hunyuan3d2.path + "')}}",
    method: "shell.run",
    params: {
      message: [
        "git clone --depth 1 " + hunyuan3d2.url + " " + hunyuan3d2.path,
        "git -C " + hunyuan3d2.path + " fetch --depth 1 origin " + hunyuan3d2.revision,
        "git -C " + hunyuan3d2.path + " checkout --detach " + hunyuan3d2.revision
      ]
    }
  }, {
    when: "{{exists('" + hunyuan3d2.path + "/.git')}}",
    method: "shell.run",
    params: {
      path: hunyuan3d2.path,
      message: [
        "git fetch --depth 1 origin " + hunyuan3d2.revision,
        "git checkout --detach " + hunyuan3d2.revision
      ]
    }
  }, {
    when: "{{!exists('" + hunyuan3d21.path + "')}}",
    method: "shell.run",
    params: {
      message: [
        "git clone --depth 1 " + hunyuan3d21.url + " " + hunyuan3d21.path,
        "git -C " + hunyuan3d21.path + " fetch --depth 1 origin " + hunyuan3d21.revision,
        "git -C " + hunyuan3d21.path + " checkout --detach " + hunyuan3d21.revision
      ]
    }
  }, {
    when: "{{exists('" + hunyuan3d21.path + "/.git')}}",
    method: "shell.run",
    params: {
      path: hunyuan3d21.path,
      message: [
        "git fetch --depth 1 origin " + hunyuan3d21.revision,
        "git checkout --detach " + hunyuan3d21.revision
      ]
    }
  }, {
    method: "shell.run",
    params: {
      conda: { path: "app/services/hunyuan3d/env", python: "3.10" },
      message: [
        "uv pip install torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128",
        "uv pip install -r app/services/hunyuan3d/requirements.txt"
      ]
    }
  }, {
    // Remove the accidental nested conda environment produced by the initial
    // native-3D migration before compiling into Maestro's real 3D runtime.
    when: "{{exists('app/services/hunyuan3d/vendor/Hunyuan3D-2/hy3dgen/texgen/custom_rasterizer/app')}}",
    method: "fs.rm",
    params: {
      path: "app/services/hunyuan3d/vendor/Hunyuan3D-2/hy3dgen/texgen/custom_rasterizer/app"
    }
  }, {
    method: "shell.run",
    params: {
      conda: { path: "../../../../../env", python: "3.10" },
      env: {
        CUDA_HOME: "{{path.resolve(path.dirname(which('nvcc')), '..')}}",
        CPATH: "{{path.resolve(path.dirname(which('nvcc')), '../targets/x86_64-linux/include')}}",
        LIBRARY_PATH: "{{path.resolve(path.dirname(which('nvcc')), '../targets/x86_64-linux/lib')}}",
        LD_LIBRARY_PATH: "{{path.resolve(path.dirname(which('nvcc')), '../targets/x86_64-linux/lib')}}"
      },
      path: "app/services/hunyuan3d/vendor/Hunyuan3D-2/hy3dgen/texgen/custom_rasterizer",
      message: "uv pip install --no-build-isolation -e ."
    }
  }, {
    method: "shell.run",
    params: {
      conda: { path: "../../../../../env", python: "3.10" },
      path: "app/services/hunyuan3d/vendor/Hunyuan3D-2/hy3dgen/texgen/differentiable_renderer",
      message: "uv pip install --no-build-isolation -e ."
    }
  }, {
    method: "shell.run",
    params: {
      conda: { path: "../../../../env", python: "3.10" },
      env: {
        CUDA_HOME: "{{path.resolve(path.dirname(which('nvcc')), '..')}}",
        CPATH: "{{path.resolve(path.dirname(which('nvcc')), '../targets/x86_64-linux/include')}}",
        LIBRARY_PATH: "{{path.resolve(path.dirname(which('nvcc')), '../targets/x86_64-linux/lib')}}",
        LD_LIBRARY_PATH: "{{path.resolve(path.dirname(which('nvcc')), '../targets/x86_64-linux/lib')}}"
      },
      path: "app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/custom_rasterizer",
      message: "uv pip install --no-build-isolation -e ."
    }
  }, {
    method: "shell.run",
    params: {
      conda: { path: "../../../../env", python: "3.10" },
      shell: "{{which('bash')}}",
      path: "app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/DifferentiableRenderer",
      message: "bash compile_mesh_painter.sh"
    }
  }, {
    when: "{{!exists('app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth')}}",
    method: "fs.download",
    params: {
      url: "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
      path: "app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth"
    }
  }, {
    method: "fs.write",
    params: {
      path: hunyuan3d2.marker,
      text: "repository=" + hunyuan3d2.url + "\nrevision=" + hunyuan3d2.revision + "\n"
    }
  }, {
    method: "fs.write",
    params: {
      path: hunyuan3d21.marker,
      text: "repository=" + hunyuan3d21.url + "\nrevision=" + hunyuan3d21.revision + "\n"
    }
  }, {
    method: "fs.write",
    params: {
      path: hunyuan3d2.marker,
      text: "repository=" + hunyuan3d2.url + "\nrevision=" + hunyuan3d2.revision + "\n"
    }
  }, {
    method: "fs.write",
    params: {
      path: hunyuan3d21.marker,
      text: "repository=" + hunyuan3d21.url + "\nrevision=" + hunyuan3d21.revision + "\n"
    }
  }]
}
