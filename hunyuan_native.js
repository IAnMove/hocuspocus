// Shared Hunyuan3D native-extension steps for install.js and update.js.
// Linux keeps the CUDA toolkit layout under targets/x86_64-linux.
// Windows only gets CUDA_HOME/CUDA_PATH so pytorch/cpp_extension can
// find include/ and lib/x64; the Linux layout does not exist there.
const cudaHome = "{{path.resolve(path.dirname(which('nvcc')), '..')}}"

const cudaEnvLinux = {
  CUDA_HOME: cudaHome,
  CPATH: "{{path.resolve(path.dirname(which('nvcc')), '../targets/x86_64-linux/include')}}",
  LIBRARY_PATH: "{{path.resolve(path.dirname(which('nvcc')), '../targets/x86_64-linux/lib')}}",
  LD_LIBRARY_PATH: "{{path.resolve(path.dirname(which('nvcc')), '../targets/x86_64-linux/lib')}}"
}

const cudaEnvWindows = {
  CUDA_HOME: cudaHome,
  CUDA_PATH: cudaHome,
  DISTUTILS_USE_SDK: 1
}

function rasterizerSteps(condaPath, rasterizerPath) {
  return [
    {
      when: "{{platform === 'linux'}}",
      method: "shell.run",
      params: {
        conda: { path: condaPath, python: "3.10" },
        env: cudaEnvLinux,
        path: rasterizerPath,
        message: "uv pip install --no-build-isolation -e ."
      }
    },
    {
      when: "{{platform === 'win32'}}",
      method: "shell.run",
      params: {
        conda: { path: condaPath, python: "3.10" },
        env: cudaEnvWindows,
        path: rasterizerPath,
        message: "uv pip install --no-build-isolation -e ."
      }
    }
  ]
}

function meshPainterSteps() {
  const painterPath = "app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/DifferentiableRenderer"
  const conda = { path: "../../../../env", python: "3.10" }
  return [
    {
      when: "{{platform === 'linux'}}",
      method: "shell.run",
      params: {
        conda,
        shell: "{{which('bash')}}",
        path: painterPath,
        message: "bash compile_mesh_painter.sh"
      }
    },
    {
      when: "{{platform === 'win32'}}",
      method: "shell.run",
      params: {
        conda,
        path: painterPath,
        message: "python \"{{path.resolve(cwd, 'scripts/windows_toolchain.py')}}\" --script ../../../../build_mesh_painter.py"
      }
    }
  ]
}

function nativeBuildSteps() {
  return [
    ...rasterizerSteps(
      "../../../../../env",
      "app/services/hunyuan3d/vendor/Hunyuan3D-2/hy3dgen/texgen/custom_rasterizer"
    ),
    {
      method: "shell.run",
      params: {
        conda: { path: "../../../../../env", python: "3.10" },
        path: "app/services/hunyuan3d/vendor/Hunyuan3D-2/hy3dgen/texgen/differentiable_renderer",
        message: "uv pip install --no-build-isolation -e ."
      }
    },
    ...rasterizerSteps(
      "../../../../env",
      "app/services/hunyuan3d/vendor/Hunyuan3D-2.1/hy3dpaint/custom_rasterizer"
    ),
    ...meshPainterSteps()
  ]
}

module.exports = {
  nativeBuildSteps
}
