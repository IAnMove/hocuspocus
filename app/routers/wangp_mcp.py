"""Opt-in MCP access to the existing Hocuspocus generation endpoints.

The request journal prevents transport retries from creating duplicate jobs. It
never executes, schedules, cancels or stores progress for canonical tasks.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
import secrets
import sqlite3
from copy import deepcopy

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from services.wangp_submission import JsonRequest
from services.workspace_commands import catalog as command_catalog

PROTOCOL = '2025-03-26'
MUTATIONS = {'generate', 'recast', 'upscale', 'organize'}
REQUEST_TOOLS = MUTATIONS | {'analyze'}
# Modes accepted by the generic /api/v1/generate handler. ``model3d`` has a
# separate /api/v1/model3d/generate contract and is intentionally not routed
# through this MCP tool.
GENERATION_MODES = ('image', 'video', 'audio', 'avatar')
LEGACY_TOOLS = REQUEST_TOOLS | {'models', 'processors', 'status', 'assets', 'collections'}


def _selected_operations(command_operations):
    entries = deepcopy(list(command_catalog()['operations'] if command_operations is None else command_operations))
    names = [entry['name'] for entry in entries]
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError('Command catalog names must be nonempty strings')
    if len(set(names)) != len(names) or LEGACY_TOOLS.intersection(names):
        raise ValueError('Command catalog names must be unique and cannot collide with legacy tools')
    return entries, frozenset(names)


def _command_tool(operation):
    # HTTP carries its operation explicitly; MCP carries it as the tool name.
    # Derive the transport projection from the same source schema.
    schema = operation['inputSchema']
    schema = {**schema, 'properties': {key: value for key, value in schema['properties'].items() if key != 'operation'},
              'required': [key for key in schema['required'] if key != 'operation']}
    return {
        'name': operation['name'], 'description': operation['description'], 'inputSchema': schema,
        'annotations': {'readOnlyHint': not operation['mutation'], 'destructiveHint': False, 'idempotentHint': True},
    }


def tool_definitions(available=None, command_operations=None):
    tools = []
    for name, description in [
        ('models', 'Discover exact model identifiers and capabilities.'),
        ('processors', 'Discover available postprocessors and hardware restrictions.'),
        ('status', 'Read the canonical status of a previously submitted job.'),
        ('assets', 'Find existing canonical media IDs and URLs. Paginate with limit and offset; never invent filenames.'),
        ('collections', 'Read existing Workspace collections and their revisions.'),
        ('organize', 'Group exact asset_ids in a Workspace collection without moving files. Create with name, or update exact workspace_id with expected_revision. Supplied asset_ids replace collection membership.'),
        ('analyze', 'Analyze up to four images or one video with the selected vision LLM. params: prompt, workspace, media=[{source: canonical URL, kind: image|video}]. Video uses 8 sampled frames and no audio. Returns text and evidence, not a generation job.'),
        ('generate', 'Submit one direct generation to Hocuspocus. Preserve literal prompts. Returns a job ID, not a finished artifact.'),
        ('recast', 'Submit Viggle character replacement: model_type=viggle_animate, video_path and ref_image_path (an edited frame of that video).'),
        ('upscale', 'Process an existing image/video using the shared Tools queue: face refinement, DLSS, RIFE or existing upscalers.'),
    ]:
        properties, required = {}, []
        if name in REQUEST_TOOLS:
            params_schema = {
                'type': 'object',
                'description': 'Parameters accepted by the corresponding /api/v1 endpoint, including workspace.',
            }
            if name == 'generate':
                params_schema.update(
                    properties={
                        'generation_mode': {
                            'type': 'string',
                            'enum': list(GENERATION_MODES),
                            'minLength': 1,
                            'description': 'Required direct generation mode; do not infer it from image_mode.',
                        },
                        'image_mode': {
                            'type': 'integer',
                            'minimum': 0,
                            'description': 'Optional native output selector; it must agree with generation_mode.',
                        },
                    },
                    required=['generation_mode'],
                )
            properties = {'request_id': {'type': 'string', 'minLength': 1, 'maxLength': 160},
                          'params': params_schema}
            required = ['request_id', 'params']
        elif name == 'status':
            properties = {'job_id': {'type': 'string', 'minLength': 1}}
            required = ['job_id']
        elif name == 'assets':
            properties = {key: {'type': 'string'} for key in ('search', 'kind', 'workspace')}
            properties.update(limit={'type': 'integer', 'minimum': 1, 'maximum': 500}, offset={'type': 'integer', 'minimum': 0})
        elif name == 'models':
            properties = {'model_type': {'type': 'string', 'description': 'Optional exact ID to get input/options instead of the catalog.'}}
        tools.append({'name': name, 'description': description,
                      'inputSchema': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False},
                      'annotations': {'readOnlyHint': name not in MUTATIONS, 'destructiveHint': False, 'idempotentHint': True}})
    operations, _ = _selected_operations(command_operations)
    for operation in operations:
        if available is not None and operation['name'] in available:
            tools.append(_command_tool(operation))
    return tools


class UncertainRequest(ValueError):
    """Legacy reservation exists without a response; do not infer admission."""


class RequestJournal:
    def __init__(self, path):
        self.path = Path(path)

    def reserve(self, request_id, digest, validate=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=15) as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT)')
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest, result FROM requests WHERE id=?', (request_id,)).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError('request_id was already used with different parameters')
                if row[1] is None:
                    raise UncertainRequest('Submission already reserved. Inspect Activity; do not resubmit with another request_id after an uncertain response.')
                return json.loads(row[1])
            if validate is not None:
                validate()
            db.execute('INSERT INTO requests VALUES (?, ?, NULL)', (request_id, digest))
        return None

    def finish(self, request_id, result):
        with sqlite3.connect(self.path, timeout=15) as db:
            db.execute('UPDATE requests SET result=? WHERE id=?', (json.dumps(result), request_id))


def _request_arguments(name, arguments):
    request_id, params = arguments.get('request_id'), arguments.get('params')
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 160 or not isinstance(params, dict):
        raise ValueError('request_id and params are required')
    if name == 'recast' and params.get('model_type') != 'viggle_animate':
        raise ValueError('MCP recast requires model_type=viggle_animate')
    digest = hashlib.sha256(json.dumps([name, params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return request_id, params, digest


def _validate_generate_params(params):
    mode = params.get('generation_mode')
    if not isinstance(mode, str) or not mode:
        raise ValueError('MCP generate requires a non-empty generation_mode')
    if mode not in GENERATION_MODES:
        modes = ', '.join(GENERATION_MODES)
        raise ValueError(f'MCP generate generation_mode must be one of: {modes}')
    if 'image_mode' not in params:
        return
    image_mode = params['image_mode']
    if isinstance(image_mode, bool) or not isinstance(image_mode, int) or image_mode < 0:
        raise ValueError('MCP generate image_mode must be a non-negative integer')
    if mode == 'image' and image_mode == 0:
        raise ValueError('MCP generate image mode requires image_mode > 0 when supplied')
    if mode != 'image' and image_mode != 0:
        raise ValueError(f'MCP generate {mode} mode requires image_mode=0')


def _prepare_generate_params(params):
    """Make the explicit MCP mode reach WanGP's native output switch."""
    if 'image_mode' not in params:
        params['image_mode'] = 1 if params.get('generation_mode') == 'image' else 0


def create_wangp_mcp_router(*, handlers, journal_path, token_getter=None, command_operations=None):
    router = APIRouter()
    journal = RequestJournal(journal_path)
    token_getter = token_getter or (lambda: os.environ.get('HOCUS_MCP_TOKEN', ''))

    operations, operation_names = _selected_operations(command_operations)
    callable_names = LEGACY_TOOLS | operation_names

    async def call_tool(name, arguments):
        if not isinstance(name, str) or name not in callable_names or not callable(handlers.get(name)) or not isinstance(arguments, dict):
            raise ValueError('Unknown tool or invalid arguments')
        if name in operation_names:
            result = handlers[name](arguments)
            return await result if inspect.isawaitable(result) else result
        if name in REQUEST_TOOLS:
            request_id, params, digest = _request_arguments(name, arguments)
            validate = (lambda: _validate_generate_params(params)) if name == 'generate' else None
            try:
                existing = journal.reserve(request_id, digest, validate=validate)
            except UncertainRequest as uncertain:
                # Only collection commands can currently prove their effect and
                # receipt were committed together. Preserve uncertainty for all
                # older/unlinked reservations and generation admissions.
                if name != 'organize' or 'commands.receipt' not in handlers:
                    raise
                try:
                    proof = handlers['commands.receipt']({'version': 1, 'input': {'intent_id': request_id}})
                    proof = await proof if inspect.isawaitable(proof) else proof
                except HTTPException as error:
                    if error.status_code == 404:
                        raise uncertain from error
                    raise
                if not isinstance(proof, dict) or proof.get('commandId') != request_id:
                    raise uncertain
                # Re-enter the domain operation only after finding the receipt;
                # its digest check must prove the same parameters before replay.
                existing = None
            if existing is not None:
                return existing
            params = dict(params)
            if name == 'generate':
                _prepare_generate_params(params)
            from services.generation_provenance import normalize_submission_provenance
            provenance = normalize_submission_provenance(params.get('provenance'), trusted_tool='external_agent')
            provenance.update(actor='user', capability=name)
            provenance['command']['command_id'] = request_id
            params['provenance'] = provenance
            try:
                result = handlers[name](JsonRequest(params, trusted_tool='external_agent'))
                if inspect.isawaitable(result):
                    result = await result
            except HTTPException as error:
                if error.status_code >= 500:
                    raise  # Keep uncertain admissions recoverable; never cache a storage outage as a terminal result.
                result = {'error': error.detail, 'status_code': error.status_code}
            # Unexpected failures deliberately retain the reservation. A queue
            # admission could have succeeded before its response was lost.
            journal.finish(request_id, result)
            return result
        if name == 'status':
            result = handlers[name](arguments['job_id'])
        elif name in {'assets', 'models'}:
            result = handlers[name](arguments)
        else:
            result = handlers[name]()
        return await result if inspect.isawaitable(result) else result

    async def dispatch(message):
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
        if 'id' not in message:
            return None
        request_id, method = message['id'], message.get('method')
        try:
            if method == 'initialize':
                result = {'protocolVersion': PROTOCOL, 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'hocuspocus', 'version': '1'},
                          'instructions': 'One queue: keep returned job IDs and poll status. Reuse request_id on retries; never assume generated quality from submission success.'}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': tool_definitions({name for name, handler in handlers.items() if callable(handler)}, operations)}
            elif method == 'tools/call':
                params = message.get('params') or {}
                if not isinstance(params, dict):
                    raise ValueError('Tool call params must be an object')
                value = await call_tool(params.get('name'), params.get('arguments') or {})
                result = {
                    'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}],
                    'isError': _tool_result_is_error(value),
                }
                if params.get('name') in operation_names and isinstance(value, dict):
                    result['structuredContent'] = value
            else:
                return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': 'Method not found'}}
            return {'jsonrpc': '2.0', 'id': request_id, 'result': result}
        except (ValueError, KeyError, TypeError, HTTPException) as error:
            detail = error.detail if isinstance(error, HTTPException) else str(error)
            params = message.get('params') or {}
            if method == 'tools/call' and isinstance(params, dict) and isinstance(params.get('name'), str) and params['name'] in operation_names:
                problem = detail if isinstance(detail, dict) else {'code': 'invalid_command', 'message': str(detail), 'retryable': False}
                failed = {'version': 1, 'status': 'failed', 'error': problem}
                return {'jsonrpc': '2.0', 'id': request_id, 'result': {
                    'isError': True, 'structuredContent': failed,
                    'content': [{'type': 'text', 'text': json.dumps(failed, ensure_ascii=False)}],
                }}
            return {'jsonrpc': '2.0', 'id': request_id, 'result': {'isError': True, 'content': [{'type': 'text', 'text': str(detail)}]}}

    @router.post('/api/v1/wangp/mcp', include_in_schema=False)
    @router.post('/api/v1/mcp')
    async def mcp(request: Request):
        token = token_getter()
        if not token:
            raise HTTPException(503, 'External agent access is disabled; configure HOCUS_MCP_TOKEN')
        if not secrets.compare_digest(request.headers.get('authorization', ''), f'Bearer {token}'):
            raise HTTPException(401, 'Invalid MCP credentials')
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
            raise HTTPException(403, 'Origin is not permitted')
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}, status_code=400)
        messages = payload if isinstance(payload, list) else [payload]
        if not 1 <= len(messages) <= 32:
            raise HTTPException(400, 'Invalid batch size')
        results = [result for message in messages if (result := await dispatch(message)) is not None]
        if not results:
            return Response(status_code=202)
        return JSONResponse(results if isinstance(payload, list) else results[0])

    @router.get('/api/v1/wangp/mcp', include_in_schema=False)
    @router.get('/api/v1/mcp')
    async def no_stream():
        return Response(status_code=405, headers={'Allow': 'POST'})

    return router


def _tool_result_is_error(value):
    if not isinstance(value, dict):
        return False
    if value.get('error') is not None:
        return True
    status = value.get('status')
    if isinstance(status, str) and status.strip().casefold() == 'failed':
        return True
    status_code = value.get('status_code')
    if isinstance(status_code, bool):
        return False
    if isinstance(status_code, (int, float)):
        return status_code >= 400
    if isinstance(status_code, str):
        try:
            return int(status_code.strip()) >= 400
        except ValueError:
            return False
    return False
