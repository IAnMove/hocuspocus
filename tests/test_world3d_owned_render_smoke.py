"""Explicit CPU Chromium/FFmpeg smoke against the production build.

RUN_WORLD3D_RENDER_SMOKE=1 pytest -q tests/test_world3d_owned_render_smoke.py
Requires ui build, Node, installed Playwright Chromium, ffmpeg and ffprobe.
"""
import base64
import functools
import json
import os
from pathlib import Path
import struct
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from services.scene_recording import probe_scene_recording_output
from services.world3d_export import export_plan, playwright_module, run_owned_browser, mux_frame_sequence
from tests.test_world3d_export import _document


def _triangle_glb():
    positions = struct.pack('<9f', -0.8, 0, 0, 0.8, 0, 0, 0, 1.6, 0)
    data = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'material': 0}]}],
            'materials': [{'doubleSided': True, 'emissiveFactor': [1, 0.05, 0.01]}],
            'buffers': [{'byteLength': len(positions), 'uri': 'data:application/octet-stream;base64,' + base64.b64encode(positions).decode()}],
            'bufferViews': [{'buffer': 0, 'byteLength': len(positions)}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3', 'min': [-0.8, 0, 0], 'max': [0.8, 1.6, 0]}]}
    payload = json.dumps(data).encode()
    payload += b' ' * (-len(payload) % 4)
    return struct.pack('<III', 0x46546C67, 2, 20 + len(payload)) + struct.pack('<II', len(payload), 0x4E4F534A) + payload


@pytest.mark.skipif(os.environ.get('RUN_WORLD3D_RENDER_SMOKE') != '1', reason='explicit built-UI Chromium smoke')
def test_real_worker_loads_glb_and_exports_24fps_from_built_ui(tmp_path):
    dist = Path(__file__).resolve().parents[1] / 'ui' / 'dist'
    assert (dist / 'world3d-render.html').is_file(), 'Build the UI first'
    requests = []
    glb = _triangle_glb()
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == '/triangle.glb':
                self.send_response(200); self.send_header('Content-Type', 'model/gltf-binary'); self.end_headers()
                self.wfile.write(glb)
            else:
                super().do_GET()
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(dist)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        doc = _document(duration=0.5, fps=24, width=256, height=144)
        doc['slots'][0].update(sourceUrl='/triangle.glb', motion={'to': [1, 0, 0]})
        snapshot = {'document': doc, 'plan': export_plan(doc), 'workspace': 'default', 'refs': []}
        (tmp_path / 'snapshot.json').write_text(json.dumps(snapshot))
        module = playwright_module()
        assert module is not None
        frames = run_owned_browser(snapshot, tmp_path, lambda: False, app_url=f'http://127.0.0.1:{server.server_port}', module=module)
        assert len(frames) == 12
        assert '/triangle.glb' in requests
        assert all(not path.startswith('/src/') for path in requests)
        assert frames[0].read_bytes() != frames[-1].read_bytes(), 'The loaded scene must advance with its clock'
        video = mux_frame_sequence(frames, tmp_path / 'render.mp4', fps=24, duration=0.5)
        info = probe_scene_recording_output(str(video))
        stream = next(item for item in info['streams'] if item['codec_type'] == 'video')
        assert stream['width'] == 256 and stream['height'] == 144
        assert stream['avg_frame_rate'] == '24/1'
        assert int(stream['nb_frames']) == 12
        assert abs(float(info['format']['duration']) - 0.5) < 0.06
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
