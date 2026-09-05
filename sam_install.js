// SAM 3.1 Segmentation Service — Install Script
// Creates a separate Python 3.12 conda env and installs SAM 3.1 + dependencies.
// Called by the Pinokio menu and update.js.
const vendors = require("./vendor_revisions")
const sam3 = vendors.sam3

module.exports = {
  run: [
    // Step 1: Clone SAM 3 repo if not already present
    {
      when: "{{!exists('" + sam3.path + "')}}",
      method: "shell.run",
      params: {
        message: [
          "git clone --depth 1 " + sam3.url + " " + sam3.path,
          "git -C " + sam3.path + " fetch --depth 1 origin " + sam3.revision,
          "git -C " + sam3.path + " checkout --detach " + sam3.revision
        ]
      }
    },
    // Step 1b: Re-select the declared revision if repo already exists.
    {
      when: "{{exists('" + sam3.path + "/.git')}}",
      method: "shell.run",
      params: {
        path: sam3.path,
        message: [
          "git fetch --depth 1 origin " + sam3.revision,
          "git checkout --detach " + sam3.revision
        ]
      }
    },
    // Step 2: Install PyTorch (CUDA 12.8) in a Python 3.12 conda env
    {
      method: "shell.run",
      params: {
        conda: {
          path: "app/services/sam/env",
          python: "3.12"
        },
        message: [
          "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128"
        ]
      }
    },
    // Step 3: Install SAM 3 package + all microservice deps from requirements.txt
    {
      method: "shell.run",
      params: {
        conda: {
          path: "app/services/sam/env",
          python: "3.12"
        },
        message: [
          "pip install app/services/sam/sam3",
          "pip install -r app/services/sam/requirements.txt"
        ]
      }
    },
    {
      method: "fs.write",
      params: {
        path: sam3.marker,
        text: "repository=" + sam3.url + "\nrevision=" + sam3.revision + "\n"
      }
    },
    // Note: SAM 3.1 model checkpoints (~1.7GB each for base + multiplex) are downloaded
    // automatically on first use. The service tries the official facebook/sam3 repo first,
    // and falls back to ungated mirrors (jetjodh/sam3, jetjodh/sam3.1) if gated access
    // is not available.
  ]
}
