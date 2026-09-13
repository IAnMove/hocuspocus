// Loaded after git pull too, so Update executes the new revision's recipes.
const runtime = require('./runtime_install')
module.exports = {
  requires: {bundle: 'ai'},
  run: [
    // Repair React before lengthy native installs, including on an unchanged Git revision.
    ...runtime.call('ui_build.js'),
    ...runtime.preflight(),
    {when: "{{!exists('app/postprocessing/seedvc/__init__.py')}}", method: 'shell.run', params: {
      message: runtime.guarded('git clone --depth 1 --branch v1.0.0 https://github.com/Blizaine/maestro-seedvc app/postprocessing/seedvc'),
    }},
    ...runtime.installEngines(['core', 'wangp', 'hunyuan3d', 'minimax_h3']),
    ...runtime.call('speech_install.js'),
    ...runtime.call('sam_install.js').map(step => ({...step,
      when: `{{args.update && exists('app/services/sam/env') && local.runtime.engines.sam.supported${step.when ? ' && (' + step.when.slice(2,-2) + ')' : ''}}}`,
    })),
    ...runtime.call('rigging_install.js').map(step => ({...step,
      when: `{{args.update && exists('app/services/rigging/env') && local.runtime.engines.rigging.supported${step.when ? ' && (' + step.when.slice(2,-2) + ')' : ''}}}`,
    })),
    {method: 'log', params: {
      raw: '{{"HocusPocus runtime recipes checked. " + Object.values(local.runtime.engines).filter(e => e.defaultInstall && !e.supported).map(e => e.label + ": " + e.reason).join(" ")}}',
    }},
    {method: 'script.return', params: {success: true}},
  ],
}
