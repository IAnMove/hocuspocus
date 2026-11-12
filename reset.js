// Wipes every install artifact so the next Install starts from scratch.
// Mirrors the directories created by install.js, runtime_setup.js,
// sam_install.js and the UI build (scripts/build_ui.py).
module.exports = {
  run: [
    { method: "fs.rm", params: { path: "app/.runtime" } },
    // Main Python venv
    { method: "fs.rm", params: { path: "app/env" } },
    // SAM 3.1 Python 3.12 conda env
    { method: "fs.rm", params: { path: "app/services/sam/env" } },
    // SAM 3 source checkout (will be re-cloned on install)
    { method: "fs.rm", params: { path: "app/services/sam/sam3" } },
    // Hunyuan3D isolated runtime, official source checkouts, and model cache
    { method: "fs.rm", params: { path: "app/services/hunyuan3d/env" } },
    { method: "fs.rm", params: { path: "app/services/hunyuan3d/vendor" } },
    { method: "fs.rm", params: { path: "app/ckpts/model3d" } },
    // MiniMax H3 isolated ComfyUI runtime and lazily-downloaded checkpoints
    { method: "fs.rm", params: { path: "app/services/minimax_h3/env" } },
    { method: "fs.rm", params: { path: "app/services/minimax_h3/vendor" } },
    // Optional FLUX 3 / Drama 3 isolated runtime and its downloaded assets.
    { method: "fs.rm", params: { path: "app/services/creation_models/env" } },
    { method: "fs.rm", params: { path: "app/services/creation_models/vendor" } },
    { method: "fs.rm", params: { path: "app/services/creation_models/input" } },
    { method: "fs.rm", params: { path: "app/services/creation_models/output" } },
    { method: "fs.rm", params: { path: "app/services/creation_models/extra_model_paths.json" } },
    { method: "fs.rm", params: { path: "app/ckpts/creation_models" } },
    { method: "fs.rm", params: { path: "app/services/rigging/env" } },
    { method: "fs.rm", params: { path: "app/services/rigging/vendor" } },
    { method: "fs.rm", params: { path: "app/services/mia/env" } },
    { method: "fs.rm", params: { path: "app/services/mia/vendor" } },
    // Seed-VC voice conversion checkout (cloned by runtime_setup.js)
    { method: "fs.rm", params: { path: "app/postprocessing/seedvc" } },
    // SAM checkpoints downloaded on first use
    { method: "fs.rm", params: { path: "app/services/sam/checkpoints" } },
    // Manually installed third-party 3D runtimes (docs/development/MODEL3D_ENGINES.md)
    { method: "fs.rm", params: { path: "app/services/model3d_runtimes" } },
    // UI build artifacts and the build lock
    { method: "fs.rm", params: { path: "ui/node_modules" } },
    { method: "fs.rm", params: { path: "ui/dist" } },
    { method: "fs.rm", params: { path: "ui/.hocus-ui-build.lock" } }
  ]
}
