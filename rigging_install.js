// UniRig Auto-Rigging Engine — Install Script
// Creates a separate Python 3.11 conda env (bpy 4.2 requires 3.11) and
// installs VAST-AI UniRig + its CUDA dependency stack. Optional: only needed
// for the AI engine in the Animate tab; the procedural engine ships with the
// normal Maestro install. Model weights (~2GB, VAST-AI/UniRig) download on
// first use. Referenced from pinokio.js like sam_install.js.
const vendors = require("./vendor_revisions")
const unirig = vendors.unirig

module.exports = {
  requires: {
    bundle: "ai"
  },
  run: [
    // Step 1: Clone UniRig if not already present
    {
      when: "{{!exists('" + unirig.path + "')}}",
      method: "shell.run",
      params: {
        message: [
          "git clone --depth 1 " + unirig.url + " " + unirig.path,
          "git -C " + unirig.path + " fetch --depth 1 origin " + unirig.revision,
          "git -C " + unirig.path + " checkout --detach " + unirig.revision
        ]
      }
    },
    // Step 1b: Re-select the declared revision if repo already exists.
    {
      when: "{{exists('" + unirig.path + "/.git')}}",
      method: "shell.run",
      params: {
        path: unirig.path,
        message: [
          "git fetch --depth 1 origin " + unirig.revision,
          "git checkout --detach " + unirig.revision
        ]
      }
    },
    // Step 2: PyTorch (CUDA 12.8) in a dedicated Python 3.11 conda env —
    // same pinned build as the Hunyuan3D env so the wheel cache is shared.
    {
      method: "shell.run",
      params: {
        conda: {
          path: "app/services/rigging/env",
          python: "3.11"
        },
        message: [
          "uv pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128"
        ]
      }
    },
    // Step 3: UniRig dependency stack (Maestro-owned copy of its
    // requirements; see app/services/rigging/requirements.txt for the diffs)
    {
      method: "shell.run",
      params: {
        conda: {
          path: "app/services/rigging/env",
          python: "3.11"
        },
        message: [
          "uv pip install -r app/services/rigging/requirements.txt"
        ]
      }
    },
    // Step 4: flash-attn — needs torch importable at build time, so it gets
    // --no-build-isolation and the CUDA toolchain env. Prebuilt wheels are
    // used when one matches torch 2.7/cu12/py3.11; otherwise this compiles.
    {
      method: "shell.run",
      params: {
        conda: {
          path: "app/services/rigging/env",
          python: "3.11"
        },
        env: {
          CUDA_HOME: "{{path.resolve(path.dirname(which('nvcc')), '..')}}"
        },
        message: [
          "uv pip install flash-attn --no-build-isolation"
        ]
      }
    },
    // Step 5: sparse-conv + PyG graph ops. spconv has no cu128-specific
    // wheel; the cu126 build runs on cu128 drivers. numpy is re-pinned LAST
    // because the stack above may bump it (UniRig requires 1.26.4).
    {
      method: "shell.run",
      params: {
        conda: {
          path: "app/services/rigging/env",
          python: "3.11"
        },
        message: [
          "uv pip install spconv-cu126",
          "uv pip install torch_scatter torch_cluster -f https://data.pyg.org/whl/torch-2.7.0%2Bcu128.html",
          "uv pip install numpy==1.26.4"
        ]
      }
    },
    // Step 6: install marker — rig_service gates the UniRig engine on this.
    {
      method: "fs.write",
      params: {
        path: "app/services/rigging/env/.maestro_rigging_v1.installed",
        text: "ok"
      }
    },
    {
      method: "fs.write",
      params: {
        path: unirig.marker,
        text: "repository=" + unirig.url + "\nrevision=" + unirig.revision + "\n"
      }
    }
  ]
}
