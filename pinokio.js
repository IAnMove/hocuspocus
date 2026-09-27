const path = require('path')
const runtimeCatalog = require('./app/runtime/profiles.json')
module.exports = {
  version: "8.0",
  title: "HocusPocus · Creation Lab",
  description: "A local creation studio, forked from Maestro, for directing persistent worlds across video, images, sound, comics and 3D. Includes recoverable Director pipelines and optimized MiniMax H3 generation. Requires an NVIDIA GPU (6GB+ VRAM).",
  icon: "hocuspocus-icon.png",
  menu: async (kernel, info) => {
    const optionalAvailable = engine => {
      // Unknown inventory is not proof of incompatibility; never hide Start.
      const rawArch = typeof kernel.arch === 'string' ? kernel.arch.toLowerCase() : ''
      const arch = rawArch === 'unknown' ? ''
        : {amd64: 'x64', x86_64: 'x64', aarch64: 'arm64'}[rawArch] || rawArch
      const gpu = typeof kernel.gpu === 'string' ? kernel.gpu.toLowerCase() : ''
      return (!kernel.platform || runtimeCatalog.engines[engine].platforms.includes(kernel.platform)) &&
        (!arch || runtimeCatalog.architectures.includes(arch)) &&
        (!gpu || gpu === 'unknown' || runtimeCatalog.accelerators.includes(gpu))
    }
    const filterOptional = items => items.filter(item =>
      item.href === 'sam_install.js' ? optionalAvailable('sam')
        : item.href === 'rigging_install.js' ? optionalAvailable('rigging') : true
    ).map(item => item.menu ? {...item, menu: filterOptional(item.menu)} : item)
    // Do not gate this menu on kernel.gpu. Pinokio can render an app menu
    // before its hardware inventory has populated that property, which would
    // hide Start from supported systems. install.js retains the documented
    // execution-time NVIDIA check for fresh installations.
    let installed = info.exists("app/env")
    let running = {
      install: info.running("install.js"),
      start: info.running("start.js"),
      start_classic: info.running("start_classic.js"),
      update: info.running("update.js"),
      ui_build: info.running("ui_build.js"),
      reset: info.running("reset.js")
    }
    if (running.install) {
      return [{
        default: true,
        icon: "fa-solid fa-plug",
        text: "Installing",
        href: "install.js",
      }]
    } else if (running.ui_build && !running.start && !running.update) {
      return [{default: true, icon: "fa-solid fa-display", text: "Preparing Web UI", href: "ui_build.js"}]
    } else if (installed) {
      if (running.start) {
        let local = info.local("start.js")
        if (local && local.url) {
          return [{
            default: true,
            icon: "fa-solid fa-rocket",
            text: "Open Web UI",
            href: local.url,
          }, {
            icon: "fa-solid fa-rocket",
            text: "Open Classic UI",
            href: local.url + "/classic",
          }, {
            icon: 'fa-solid fa-terminal',
            text: "Terminal",
            href: "start.js",
          }]
        } else {
          return [{
            icon: 'fa-solid fa-terminal',
            text: "Terminal",
            href: "start.js",
          }]
        }
      } else if (running.start_classic) {
        let local = info.local("start_classic.js")
        if (local && local.url) {
          return [{
            default: true,
            icon: "fa-solid fa-rocket",
            text: "Open Classic UI",
            href: local.url,
          }, {
            icon: 'fa-solid fa-terminal',
            text: "Terminal",
            href: "start_classic.js",
          }]
        } else {
          return [{
            icon: 'fa-solid fa-terminal',
            text: "Terminal",
            href: "start_classic.js",
          }]
        }
      } else if (running.update) {
        return [{
          default: true,
          icon: 'fa-solid fa-terminal',
          text: "Updating",
          href: "update.js",
        }]
      } else if (running.reset) {
        return [{
          default: true,
          icon: 'fa-solid fa-terminal',
          text: "Resetting",
          href: "reset.js",
        }]
      } else {
        return [{
          icon: "fa-solid fa-power-off",
          text: "Start",
          href: "start.js",
        }, {
          icon: "fa-solid fa-display",
          text: "Start (Classic UI)",
          href: "start_classic.js",
        }, {
          icon: "fa-solid fa-power-off",
          text: "Advanced",
          menu: [{
            icon: "fa-solid fa-power-off",
            text: "Compiled (Faster but may not work)",
            href: "start.js",
            params: {
              compile: true
            }
          }, {
            icon: "fa-solid fa-power-off",
            text: "Classic Compiled",
            href: "start_classic.js",
            params: {
              compile: true
            }
          }]
        }, {
          icon: "fa-regular fa-folder-open",
          text: "T2V Loras (save lora files here)",
          href: "app/loras",
          fs: true
        }, {
          icon: "fa-regular fa-folder-open",
          text: "I2V Loras (save lora files here)",
          href: "app/loras_i2v",
          fs: true
        }, {
          icon: "fa-solid fa-plug",
          text: "Update",
          href: "update.js",
        }, {
          icon: "fa-solid fa-display",
          text: "Repair Web UI",
          href: "ui_build.js",
          params: {force: true},
        }, {
          icon: "fa-solid fa-plug",
          text: "Install",
          href: "install.js",
        }, {
          // Install / re-install the SAM 3.1 segmentation service
          // (separate Python 3.12 conda env, takes ~5 min). Only
          // needed for the experimental Inpaint feature in Edit
          // mode — most users never need it, which is why install.js
          // no longer runs sam_install.js automatically. Label flips
          // to "Update Inpaint Support" once installed so users can
          // refresh SAM independently of the main app update.
          icon: "fa-solid fa-vector-square",
          text: info.exists("app/services/sam/env")
            ? "Update Inpaint Support (SAM 3.1)"
            : "Install Inpaint Support (SAM 3.1)",
          href: "sam_install.js",
        }, {
          // Install / re-install the UniRig AI auto-rigging engine
          // (separate Python 3.11 conda env; weights ~2GB download on
          // first use; needs an NVIDIA GPU with 8GB+ VRAM). Optional:
          // the Animate tab's procedural engine works without it.
          icon: "fa-solid fa-person-running",
          text: info.exists("app/services/rigging/env")
            ? "Update AI Rigging (UniRig)"
            : "Install AI Rigging (UniRig)",
          href: "rigging_install.js",
        }, {
          icon: "fa-regular fa-circle-xmark",
          text: "<div><strong>Reset</strong><div>Revert to pre-install state</div></div>",
          href: "reset.js",
          confirm: "Are you sure you wish to reset the app?"
        }].flatMap(item => filterOptional([item]))
      }
    } else {
      return [{
        default: true,
        icon: "fa-solid fa-plug",
        text: "Install",
        href: "install.js",
      }]
    }
  }
}
