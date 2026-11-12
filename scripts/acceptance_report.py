"""Build a portable, offline index from preserved live acceptance evidence."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
from urllib.parse import quote


def read_json(path: Path, errors: list[str]) -> dict | list:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        errors.append(f'{path.name}: {exc}')
        return {}


def link(root: Path, target: Path) -> str:
    return quote(target.relative_to(root).as_posix(), safe='/')


def feature_cards(root: Path, errors: list[str]) -> str:
    latest: dict[str, tuple[dict, Path]] = {}
    for path in sorted(root.rglob('features.json'), key=lambda item: item.stat().st_mtime):
        for record in read_json(path, errors):
            latest[record['id']] = (record, path.parent)
    cards = []
    for record, directory in latest.values():
        title = escape(' → '.join(record['route']))
        wizard = record['wizard']
        screenshot = link(root, directory / record['screenshot'])
        status = escape(record['status'])
        cards.append(f'''<article data-search="{title.lower()}"><h3>{title}</h3>
<p class="{status}">Acceso a pantalla: {status}. Generación: ver casos ejecutados.</p>
<a href="{screenshot}"><img loading="lazy" src="{screenshot}" alt="{title}"></a>
<p><b>Wizard: {escape(wizard['support'])}</b> · {escape(', '.join(wizard['actions']))}</p>
<p>{escape(wizard['example'])}</p><small>{escape(wizard['note'])}</small>
<details><summary>Detalle del intento</summary><pre>{escape(record.get('error') or 'Sin error de navegación registrado.')}</pre></details></article>''')
    return '\n'.join(cards)


def attempt_rows(root: Path, errors: list[str]) -> str:
    attempts: dict[Path, dict] = {}
    for path in sorted(root.rglob('run.json')):
        data = read_json(path, errors)
        for record in data.get('attempts', []):
            # Match within this portable evidence tree, not the old machine path.
            attempts[path.parent / Path(record['path']).name] = record
    for path in sorted(root.rglob('results.json')):
        attempts.setdefault(path.parent, {})
    rows = []
    for directory, record in sorted(attempts.items()):
        results = directory / 'results.json'
        data = read_json(results, errors) if results.exists() else {}
        stats = data.get('stats', {})
        status = escape(record.get('status', 'sin manifest'))
        if stats:
            status += f" · {stats.get('expected', 0)} pasan · {stats.get('unexpected', 0)} fallan · {stats.get('skipped', 0)} omitidos"
        else:
            status += ' · sin resultado Playwright; no se acredita éxito'
        report = directory / 'report' / 'index.html'
        target = report if report.exists() else results if results.exists() else directory.parent / 'run.json'
        rows.append(f'<li><a href="{link(root, target)}">{escape(str(directory.relative_to(root)))}</a> — {status}</li>')
    return '\n'.join(rows)


def generation_rows(root: Path, errors: list[str]) -> str:
    rows = []
    for path in sorted(root.rglob('*-result.json')):
        data = read_json(path, errors)
        if not isinstance(data, dict) or 'output' not in data or 'task' not in data:
            continue
        output = data['output']
        local = path.parent / output['name']
        target = local if local.exists() else path
        rows.append(f'''<li><a href="{link(root, target)}">{escape(output['name'])}</a>
· {escape(data['task']['status'])} · {data.get('bytes', 0)} bytes
· <a href="{link(root, path)}">Identidad, tarea y metadatos</a></li>''')
    return '\n'.join(rows) or '<li>Aún no hay resultados de generación verificados en este índice.</li>'


def build_report(root: Path) -> Path:
    root = root.resolve()
    errors: list[str] = []
    html = '''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HocusPocus · Auditoría de uso</title><style>
body{background:#0c1421;color:#e5edf7;font:16px/1.5 system-ui;margin:0 auto;padding:24px;max-width:1500px}a{color:#8fbdff}h1{margin-bottom:8px}input{padding:12px;width:min(90%,600px);background:#18253a;color:white;border:1px solid #6d84a8;border-radius:8px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:18px}article{background:#152235;border:1px solid #344761;border-radius:12px;padding:16px;min-width:0}img{width:100%;max-height:320px;object-fit:contain;background:#050a10}small{color:#adbed3}pre{white-space:pre-wrap;overflow-wrap:anywhere}.passed{color:#86ddb2}.failed{color:#ffb398}li{overflow-wrap:anywhere}
</style><h1>HocusPocus · Auditoría de uso</h1>
<p>Capturas, resultados y acceso desde Ask to the Wizard. El inventario muestra la última captura de cada función; conserva los intentos anteriores en sus informes.</p>
<p><b>Alcance:</b> una pantalla accesible no acredita generación ni exportación. «registered» significa capacidad encontrada en el registro, «partial» soporte parcial y «manual» controles manuales. La ejecución real del Wizard requiere su traza y el resultado del caso.</p>
GUIDE
<h2>Casos e intentos</h2><ul>ATTEMPTS</ul><h2>Resultados verificados</h2><ul>RESULTS</ul>
WARNINGS
<h2>Inventario de pantallas</h2><p><input id="filter" aria-label="Filtrar funciones" placeholder="Buscar: música, Video 3D, Tools…"></p><div class="grid">CARDS</div>
<script>document.querySelector('#filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('article').forEach(c=>c.hidden=!c.textContent.toLowerCase().includes(q))})</script></html>'''
    html = html.replace('ATTEMPTS', attempt_rows(root, errors)).replace('RESULTS', generation_rows(root, errors)).replace('CARDS', feature_cards(root, errors))
    guide = root / 'WIZARD_COVERAGE_AUDIT.md'
    html = html.replace('GUIDE', f'<p><a href="{link(root, guide)}">Cobertura y acciones del Wizard</a></p>' if guide.exists() else '')
    warnings = '<h2>Evidencia incompleta</h2><ul>' + ''.join(f'<li>{escape(error)}</li>' for error in errors) + '</ul>' if errors else ''
    html = html.replace('WARNINGS', warnings)
    target = root / 'index.html'
    target.write_text(html, encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, help='Existing evidence directory; no files are removed')
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error('root must be an existing evidence directory')
    print(build_report(args.root))
