"""Prop generation, import and approval; all public transports share these handlers."""
from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from PIL import Image
from starlette.concurrency import run_in_threadpool

from services.character_styles import character_style, screen_for
from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent
from services.media_paths import resolve_permitted_media_path
from services.prop_library import LOCK, MAX_PROPS, atomic_json, read_library, update_library, get_prop, validate_prop
from services.scene_documents import WORKSPACE_RE
from services.set_generation import generate_batch, require_result
from services.set_molds import defaults

READS = {'props.list', 'props.get', 'props.status'}
DESCRIPTIONS = {
    'create': 'Generate isolated 2.5D prop candidates at a real height in metres, crop their backgrounds and store them unapproved. Returns a job; poll props.status.',
    'import': 'Import an existing PNG as a prop with heightM. Existing transparent images retain their pixels.',
    'status': 'Read a prop-generation job and its candidate ids.',
    'approve': 'Approve a prop candidate for use in a scene.',
    'reject': 'Reject a prop candidate without removing its image.',
    'list': 'List workspace props, optionally filtered by style and text.',
    'get': 'Read one prop including real height, image and provenance.',
    'delete': 'Remove a prop record from the library; existing scene images remain available.',
}


def command_catalog():
    properties = {'workspace': {'type': 'string'}, 'name': {'type': 'string'}, 'description': {'type': 'string'},
        'heightM': {'type': 'number', 'minimum': .01, 'maximum': 30}, 'style': {'type': 'string'}, 'refs': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 3},
        'candidates': {'type': 'integer', 'minimum': 1, 'maximum': 8}, 'id': {'type': 'string'}, 'job_id': {'type': 'string'},
        'source': {'type': 'string'}, 'query': {'type': 'string'}, 'base_revision': {'type': 'integer', 'minimum': 0}, 'approved': {'type': 'boolean'}}
    required = {'create': ['name', 'description', 'heightM'], 'import': ['name', 'source', 'heightM'], 'status': ['job_id'], 'list': []}
    output = []
    for action, description in DESCRIPTIONS.items():
        name = f'props.{action}'; mutation = name not in READS
        envelope = {'version': {'const': 1}, 'input': {'type': 'object', 'properties': properties, 'additionalProperties': False,
            'required': ['workspace', *required.get(action, ['id'])]}}
        if mutation:
            envelope['intent_id'] = {'type': 'string'}
        output.append({'name': name, 'version': 1, 'domain': 'scenes', 'mutation': mutation, 'destructive': action == 'delete',
            'description': description, 'inputSchema': {'type': 'object', 'additionalProperties': False, 'properties': envelope, 'required': list(envelope)}})
    return output


def prop_prompt(description: str, style: str) -> tuple[str, str, str]:
    config = defaults()['prop']
    flat = any(word in style.lower() for word in config['flatStyles'])
    screen = screen_for(description)
    background = screen if config['background']['flat_styles' if flat else 'painted_or_realistic'] == 'screen' else 'grey'
    try:
        preset = character_style(style)
        prompt, negative = preset['prop'].replace('{description}', description), preset['negative']
    except KeyError:
        prompt, negative = f'{style}. {description}', ''
    return f'{prompt}. Single object, isolated, centered, full object visible, front view, plain flat {background} background, no shadow, no floor', f'{negative}, text, watermark, people, hands', background


class PropService:
    def __init__(self, workspace_dir, uploads_dir, call, *, inline=False):
        self.workspace_dir, self.uploads_dir, self.call, self.inline = workspace_dir, uploads_dir, call, inline
        self.active: set[str] = set()

    def _root(self, data):
        workspace = data.get('workspace')
        if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
            raise ValueError('workspace required')
        return Path(self.workspace_dir(workspace))

    def _file(self, source, data):
        return resolve_permitted_media_path(source, uploads_root=str(self.uploads_dir()), workspace_root=str(self._root(data)), kinds=('image',), workspace_name=data['workspace'])

    def _record(self, data, id_, file, provenance):
        row = {'id': id_, 'name': data['name'], 'description': data.get('description', data['name']), 'heightM': data['heightM'],
            'file': file, 'anchor': 'bottom', 'style': data.get('style', ''), 'facing': 'front', 'approved': False,
            'provenance': {**provenance, 'date': datetime.now(timezone.utc).isoformat()}}
        validate_prop(row)
        return row

    def _cut(self, source, data, tag):
        result = require_result(self.call('image.remove_background', {'version': 1, 'intent_id': tag,
            'input': {'workspace': data['workspace'], 'source': source, 'method': 'auto', 'crop': True}}))
        return result['file'], result.get('report', {})

    def _import(self, data):
        root = self._root(data); source = self._file(data['source'], data)
        id_ = 'prop-' + uuid.uuid4().hex[:12]
        with Image.open(source) as image:
            if image.format != 'PNG':
                raise ValueError('props.import requires a PNG')
            transparent = image.convert('RGBA').getchannel('A').getextrema()[0] < 255
            if transparent:
                root.mkdir(parents=True, exist_ok=True); file = f'{id_}.png'; image.save(root/file)
        if not transparent:
            file, _ = self._cut(source, data, id_)
        row = self._record(data, id_, file, {'method': 'import', 'source': Path(source).name})
        result = update_library(root, lambda rows: rows.append(row), data.get('base_revision'))
        return {'prop': row, 'revision': result['revision']}

    def _job_path(self, root, id_):
        if not re.fullmatch(r'props-[a-f0-9]{16}', str(id_)):
            raise ValueError('invalid prop job id')
        return root/'.prop-jobs'/f'{id_}.json'

    def _start(self, data):
        root = self._root(data)
        count = data.get('candidates', defaults()['prop']['candidates'])
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
            raise ValueError('candidates must be between 1 and 8')
        self._record(data, 'validation', '', {})
        library = read_library(root)
        if data.get('base_revision', library['revision']) != library['revision']:
            raise HTTPException(409, 'revision_conflict')
        if len(library['props'])+count > MAX_PROPS:
            raise ValueError('prop library allows at most 500 objects')
        job = {'job_id': f'props-{uuid.uuid4().hex[:16]}', 'status': 'queued', 'candidates': [], 'createdAt': time.time()}
        atomic_json(self._job_path(root, job['job_id']), job)
        self.active.add(job['job_id'])
        if self.inline:
            self._produce(data, job, count)
        else:
            threading.Thread(target=self._produce, args=(data, job, count), daemon=True).start()
        return dict(job)

    def _produce(self, data, job, count):
        root = self._root(data); path = self._job_path(root, job['job_id']); started = time.monotonic()
        try:
            job['status'] = 'running'; atomic_json(path, job)
            prompt, negative, _ = prop_prompt(data['description'], data.get('style', ''))
            batch = generate_batch(self.call, data['workspace'], [{'prompt': prompt, 'negative': negative, 'resolution': defaults()['prop']['resolution'],
                'refs': data.get('refs', []), 'candidates': count}], job['job_id'])
            for index, source in enumerate(batch[0]['files']):
                id_ = f"prop-{job['job_id'][6:]}-{index+1}"
                file, report = self._cut(source, data, id_)
                row = self._record(data, id_, file, {**batch[0]['provenance'], 'report': report})
                update_library(root, lambda rows: rows.append(row))
                job['candidates'].append(id_); atomic_json(path, job)
            job['status'] = 'completed'
        except Exception as error:
            job.update(status='failed', error=str(error))
        finally:
            job['seconds'] = round(time.monotonic()-started, 3); atomic_json(path, job); self.active.discard(job['job_id'])

    def _effect(self, operation, data):
        root = self._root(data)
        if operation == 'props.create': return self._start(data)
        if operation == 'props.import': return self._import(data)
        if operation == 'props.status':
            import json
            job = json.loads(self._job_path(root, data['job_id']).read_text())
            if job['status'] in {'queued', 'running'} and job['job_id'] not in self.active:
                job.update(status='failed', error='Server restarted during prop generation')
            return job
        library = read_library(root)
        if operation == 'props.list':
            rows = [row for row in library['props'] if (not data.get('style') or row['style'] == data['style'])
                and data.get('query', '').lower() in (row['name']+' '+row['description']).lower()
                and ('approved' not in data or row['approved'] == data['approved'])]
            return {**library, 'props': rows}
        row = get_prop(root, data['id'])
        if operation == 'props.get': return {'prop': row, 'revision': library['revision']}
        def change(rows):
            found = next(r for r in rows if r['id'] == data['id'])
            if operation == 'props.delete': rows.remove(found)
            else: found.update(approved=operation == 'props.approve', rejected=operation == 'props.reject')
        return update_library(root, change, data.get('base_revision'))

    def execute(self, operation, arguments):
        try:
            if operation not in {f'props.{a}' for a in DESCRIPTIONS} or arguments.get('version') != 1:
                raise ValueError('unknown operation or version')
            data = arguments['input']; root = self._root(data)
            with LOCK:
                if operation in READS:
                    result = self._effect(operation, data)
                else:
                    intent = check_intent_id(arguments.get('intent_id')); digest = intent_digest(data)
                    result = load_intent(root, operation, intent, digest)
                    if result is None:
                        result = self._effect(operation, data); store_intent(root, operation, intent, digest, result)
            return {'version': 1, 'operation': operation, 'status': 'completed', 'result': result}
        except IntentConflict as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, KeyError, FileNotFoundError) as error:
            raise HTTPException(422, str(error)) from error

    def handlers(self):
        def handler(name):
            async def run(arguments):
                return await run_in_threadpool(self.execute, name, arguments)
            return run
        return {f'props.{action}': handler(f'props.{action}') for action in DESCRIPTIONS}
