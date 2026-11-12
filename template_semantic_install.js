// Optional CPU weights for template search. The studio env already has
// transformers. This downloads weights only; it does not create a venv.
const runtime = require('./runtime_install')
const script = '{{path.resolve(cwd, "scripts/download_template_semantic.py")}}'
const download = (python) => ({
  method: 'shell.run',
  params: {
    env: {CUDA_VISIBLE_DEVICES: ''},
    message: runtime.guarded(`${python} "${script}"`),
  },
})
module.exports = {
  run: [
    ...runtime.preflight('template_semantic'),
    {when: "{{platform === 'win32'}}", ...download('{{path.resolve(cwd, "app/env/Scripts/python.exe")}}')},
    {when: "{{platform !== 'win32'}}", ...download('{{path.resolve(cwd, "app/env/bin/python")}}')},
    {method: 'script.return', params: {success: true}},
  ],
}
