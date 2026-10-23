// Install and Update share the same platform recipes and dependency checks.
const runtime = require("./runtime_install")
const components = require("./install_components")
module.exports = {
  requires: {bundle: "ai"},
  run: [
    ...runtime.preflight(),
    // The core/remote studio has no optional engines, so it is not asked.
    ...components.chooseSteps(),
    // The core/remote studio downloads no local models, so it skips the Hub login.
    ...runtime.hfLogin("{{local.runtime.engines.wangp.supported}}"),
    ...runtime.call("runtime_setup.js", {update: false, extras: "{{local.extras || ''}}"}),
    {method: "input", params: {
      title: "Installation completed",
      description: "{{local.runtime.summary.join(' ')}} Click Start."
    }}
  ]
}
