// Install and Update share the same platform recipes and dependency checks.
const runtime = require("./runtime_install")
module.exports = {
  requires: {bundle: "ai"},
  run: [
    ...runtime.preflight(),
    // The core/remote studio downloads no local models, so it skips the Hub login.
    ...runtime.hfLogin("{{local.runtime.engines.wangp.supported}}"),
    ...runtime.call("runtime_setup.js", {update: false}),
    {method: "input", params: {
      title: "Installation completed",
      description: "Check the runtime report above, then click Start."
    }}
  ]
}
