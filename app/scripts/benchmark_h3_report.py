"""Render a reviewable, self-contained comparison through Hocuspocus's file API."""
from __future__ import annotations
import argparse
import html
import json
from pathlib import Path
from urllib.parse import quote


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def render(records: Path, destination: Path):
    rows = read_json(records / 'matrix.json', [])
    selected = read_json(records / 'selected-indices.json', None)
    if selected is not None:
        from benchmark_h3 import matrix
        selected_ids = {row['id'] for index, row in enumerate(matrix()) if index in selected}
        rows = [row for row in rows if row['id'].removesuffix('-futurama') in selected_ids]
    prompt = read_json(records / 'prompt-faithful.json', {}).get('source_prompt', '')
    futurama_prompt = read_json(records / 'futurama-prompt-faithful.json', {}).get('source_prompt', '')
    cards = []
    completed = 0
    for index, row in enumerate(rows):
        folder = records / row['id']
        record = read_json(folder / 'result.json', {})
        status = record.get('result') or read_json(folder / 'status.json', {})
        assessment = read_json(folder / 'assessment.json', {})
        state = status.get('status', 'pendiente')
        if record.get('error'):
            state = 'error'
        files = status.get('output_files') or []
        completed += bool(files)
        videos = ''.join('<video controls preload="metadata" src="/api/v1/file/' +
            quote(str(name), safe='') + '?workspace=h3_benchmark"></video>' for name in files)
        duration = record.get('elapsed_seconds')
        timing = f'{duration:.1f} s' if isinstance(duration, (float, int)) else 'Pending'
        attention = assessment.get('effective_attention', row['attention'])
        notes = assessment.get('notes', 'Quality awaiting review.')
        error = record.get('error') or status.get('error') or ''
        details = dict(row)
        details['effective_attention'] = attention
        memory = read_json(folder / 'memory.json', {})
        details['memory'] = memory
        details['phase_timings'] = status.get('task_timings', [])
        phases = [phase for task in status.get('task_timings', []) for phase in task.get('phase_timings', [])]
        phase_text = ' · '.join(f'{phase["phase"]}: {phase["seconds"]:.1f} s' for phase in phases)
        peaks = memory.get('peak_bytes', {})
        memory_text = ' · '.join(f'{label}: {peaks[key] / 2**30:.2f} GiB' for key, label in [('process_pss_bytes', 'Process RAM (PSS) peak'), ('gpu0_process_used_bytes', 'Process VRAM peak'), ('process_swap_bytes', 'Process swap peak'), ('system_ram_unavailable_bytes', 'System RAM peak'), ('gpu0_total_used_bytes', 'System VRAM peak'), ('system_swap_used_bytes', 'System swap peak')] if key in peaks and key not in memory.get('invalid_peak_fields', [])) or 'Memory: not measured yet'
        if memory.get('invalid_peak_fields'):
            memory_text += ' · Aggregated process RAM: anomalous sample; see system RAM'
        if 'server_pss_bytes' in peaks and 'server_pss_bytes' not in memory.get('invalid_peak_fields', []):
            memory_text += f' · Server RAM without helpers: {peaks["server_pss_bytes"] / 2**30:.2f} GiB'
            if memory.get('server_metrics_partial'):
                memory_text += ' (partial record)'
        scene = 'Futurama · second run' if row.get('scene') == 'futurama' else 'Seinfeld'
        if row.get('ending'):
            scene += f" · soundscape {row['soundscape']} · ending {row['ending']}"
        if assessment:
            details['assessment'] = assessment
        cards.append(f'''<article data-state="{html.escape(state)}" data-style="{row['style']}">
<h2>{index + 1}. {html.escape(row['model'])}</h2>
<p>{html.escape(row['preset'] or 'No Turbo adapter')} · {row['steps']} steps · {html.escape(attention)} · {row['frames']} frames · memory profile {row.get('profile', 3)}</p>
<p><strong>{html.escape(state)}</strong> · {timing} · {row['style']} · audio {row['audio']}</p>
<p>{scene}</p><p>{memory_text}</p><p>{html.escape(phase_text)}</p>{videos}<p>{html.escape(notes)}</p><p class="error">{html.escape(str(error))}</p>
<details><summary>Configuration and assessment</summary><pre>{html.escape(json.dumps(details, ensure_ascii=False, indent=2))}</pre></details></article>''')
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>H3 · Seinfeld comparison</title><style>
body{margin:auto;padding:24px;max-width:1250px;background:#10141c;color:#ecf0f7;font:16px/1.5 system-ui}h1{margin-bottom:8px}a{color:#8dd4ff}header{max-width:950px}blockquote{margin:16px 0;padding:14px;background:#202938;border-radius:8px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:18px;margin-top:24px}article{padding:18px;background:#1b2431;border-radius:12px;overflow:hidden}h2{font-size:18px;overflow-wrap:anywhere}p{margin:8px 0}video{width:100%;background:#000;border-radius:6px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.error{color:#ffb6b6}select,button{font:inherit;padding:6px 12px;margin:8px;color:inherit;background:#26344a;border:1px solid #6f86a9;border-radius:6px}details{margin-top:12px}
</style><header><h1>H3 · Seinfeld and Futurama</h1>
<p>Experimental Hocuspocus copy. Seed 20260906, 864 × 480 and Spanish dialogue. Faithful and creative modes start from the same text; reference tests reuse a single image.</p>
<p>Total time includes loading and preparation. Peaks are sampled every second, not guaranteed minimum requirements. Process RAM and VRAM are distinguished from whole-system usage. Diagnostic attempts are kept separately. No configuration is assumed to eliminate babbling.</p>
<p><a href="/">Open Hocuspocus</a> · <span>COMPLETED videos available out of TOTAL tests</span></p>
<blockquote>PROMPT</blockquote><blockquote>FRYPROMPT</blockquote><label>Mode <select id="style"><option value="all">All</option><option value="faithful">Faithful</option><option value="creative">Creative</option></select></label><button onclick="location.reload()">Refresh results</button></header><main>CARDS</main>
<script>document.querySelector('#style').addEventListener('change', e => {document.querySelectorAll('article').forEach(card => {card.hidden = e.target.value !== 'all' && card.dataset.style !== e.target.value;card.style.display = card.hidden ? 'none' : '';});});</script></html>'''
    if rows and all(row.get('ending') for row in rows):
        document = document.replace('H3 · Seinfeld and Futurama', 'H3 · Eight 4-step dialogue tests')
        document = document.replace('Faithful and creative modes start from the same text; reference tests reuse a single image.', 'We compare two lines against three lines (the extra one written by hand), soundscape and ending direction. No video uses Semantic Bridge.')
        document = document.replace('<blockquote>FRYPROMPT</blockquote>', '<p><a href="/api/v1/file/h3-benchmark.html?workspace=h3_benchmark">Previous comparison and 14 min 18 s control</a></p>')
    document = document.replace('COMPLETED', str(completed)).replace('TOTAL', str(len(rows)))
    diagnostics = []
    for path in sorted(records.glob('*-diagnostics/*/result.json')):
        diagnostic = read_json(path, {})
        result = diagnostic.get('result', {})
        review = read_json(path.parent / 'assessment.json', {}).get('notes', '')
        wall = diagnostic.get('elapsed_seconds')
        timing = f'{wall:.1f} s' if isinstance(wall, (int, float)) else ''
        for name in result.get('output_files') or []:
            diagnostics.append('<article><h2>Diagnostic result · PDD 8 / SDPA</h2><p>' + html.escape(timing + ' · ' + review) + '</p><p>Sol switched to dense attention in this attempt. Kept to review image and Spanish; the corrected version is measured separately.</p><video controls preload="metadata" src="/api/v1/file/' + quote(str(name), safe='') + '?workspace=h3_benchmark"></video></article>')
    document = document.replace('FRYPROMPT', html.escape(futurama_prompt)).replace('PROMPT', html.escape(prompt)).replace('CARDS', ''.join(diagnostics + cards))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document)
    print(f'{completed}/{len(rows)} output rows: {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('records', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    render(args.records, args.destination)
