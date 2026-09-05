#!/usr/bin/env node
/**
 * TypeScript compiler-AST extractor for the bounded Story Lab -> Director
 * audio flow.  This is intentionally syntax-only: the graph documents
 * observable call sites and references without pretending to be a complete
 * type-resolved dependency graph.
 *
 * The Python entry point invokes this file and merges its fragment into the
 * schema-v1 document.  Keeping the frontend extractor independent also lets
 * the UI test suite exercise it without importing Python.
 */

import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import * as ts from 'typescript'

export const TS_SCOPE_FILES = [
  'ui/src/features/stories/StoryLabPanel.tsx',
  'ui/src/components/Sidebar/DirectorPanel.tsx',
  'ui/src/components/Sidebar/DirectorChat.tsx',
  'ui/src/features/stories/storyProductionController.ts',
  'ui/src/api/director.ts',
  'ui/src/api/outputs.ts',
  'ui/src/stores/useStore.ts',
]

const API_FUNCTIONS = [
  'adoptAudio',
  'uploadAudio',
  'trimAudio',
  'startAudioAnalysisJob',
  'getServerMediaReference',
  'getPlayableFileUrl',
  'getFileUrl',
]
const API_FILE_BY_FUNCTION = {
  adoptAudio: 'ui/src/api/director.ts',
  uploadAudio: 'ui/src/api/director.ts',
  trimAudio: 'ui/src/api/director.ts',
  startAudioAnalysisJob: 'ui/src/api/director.ts',
  getServerMediaReference: 'ui/src/api/outputs.ts',
  getPlayableFileUrl: 'ui/src/api/outputs.ts',
  getFileUrl: 'ui/src/api/outputs.ts',
}
const STORE_ACTIONS = [
  'directorAdoptAndAnalyze',
  'directorUploadAndAnalyze',
  'directorLoadAudioSource',
  'directorAnalyzeAndPlan',
]
const API_ROUTE_LITERALS = {
  adoptAudio: '/api/v1/audio/adopt',
  uploadAudio: '/api/v1/upload-audio',
  trimAudio: '/api/v1/audio/trim',
  startAudioAnalysisJob: '/api/v1/audio/analyze/jobs',
  getFileUrl: '/api/v1/file/',
}
const UI_FILES = {
  'ui.story_lab_panel': ['ui/src/features/stories/StoryLabPanel.tsx', 'ui'],
  'ui.director_panel': ['ui/src/components/Sidebar/DirectorPanel.tsx', 'ui'],
  'ui.director_chat': ['ui/src/components/Sidebar/DirectorChat.tsx', 'ui'],
  'ctrl.story_production_controller': [
    'ui/src/features/stories/storyProductionController.ts',
    'controller',
  ],
}
const CONTROLLER_ENTRY = 'loadStoryMusicVideoProduction'

const LIMITATIONS = [
  'TypeScript extraction is compiler-AST based but does not perform type or module resolution.',
  'Call matching uses syntactic receiver and import names; same-name aliases or re-exports may be omitted.',
  'Aliased calls, computed property names, and runtime dispatch may be absent.',
  'Static call-site multiplicity is not execution count and does not prove runtime behaviour.',
  'The combined source hash identifies bytes only; it does not prove semantic completeness or correctness.',
]

function normalizeFile(file) {
  return file.split(path.sep).join('/')
}

function evidence(sourceFile, node, file) {
  const start = node.getStart(sourceFile)
  const position = sourceFile.getLineAndCharacterOfPosition(start)
  return {
    file: normalizeFile(file),
    line: position.line + 1,
    column: position.character + 1,
  }
}

function evidenceKey(value) {
  return `${value.file}:${value.line}:${value.column}`
}

function mergeEvidence(target, values) {
  const seen = new Set(target.map(evidenceKey))
  for (const value of values) {
    const key = evidenceKey(value)
    if (!seen.has(key)) {
      target.push(value)
      seen.add(key)
    }
  }
  target.sort((left, right) => (
    left.file.localeCompare(right.file)
    || left.line - right.line
    || left.column - right.column
  ))
}

function nameText(node) {
  if (!node) return null
  if (ts.isIdentifier(node) || ts.isStringLiteral(node)) return node.text
  return null
}

function declarationName(node) {
  return nameText(node.name)
}

function isFunctionLike(node) {
  return ts.isFunctionDeclaration(node)
    || ts.isFunctionExpression(node)
    || ts.isArrowFunction(node)
    || ts.isMethodDeclaration(node)
}

function functionLikeForName(sourceFile, name) {
  const candidates = []
  function visit(node) {
    if (isFunctionLike(node) && declarationName(node) === name && node.body) {
      candidates.push(node)
    }
    if (ts.isVariableDeclaration(node)
      && nameText(node.name) === name
      && node.initializer
      && isFunctionLike(node.initializer)
      && node.initializer.body) {
      candidates.push(node.initializer)
    }
    if (ts.isPropertyAssignment(node)
      && nameText(node.name) === name
      && isFunctionLike(node.initializer)
      && node.initializer.body) {
      candidates.push(node.initializer)
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  if (candidates.length > 1) {
    throw new Error(`Ambiguous required TypeScript function ${name}`)
  }
  return candidates[0] || null
}

function visitAll(node, callback) {
  function visit(current) {
    callback(current)
    ts.forEachChild(current, visit)
  }
  visit(node)
}

function propertyName(node) {
  if (!ts.isPropertyAccessExpression(node)) return null
  return node.name.text
}

function expressionRoot(node) {
  if (ts.isIdentifier(node)) return node.text
  if (ts.isPropertyAccessExpression(node)) return expressionRoot(node.expression)
  if (ts.isCallExpression(node)) return expressionRoot(node.expression)
  return null
}

function callReference(call) {
  if (!ts.isCallExpression(call)) return null
  if (ts.isIdentifier(call.expression)) {
    return { name: call.expression.text, receiver: 'bare' }
  }
  if (!ts.isPropertyAccessExpression(call.expression)) return null
  return {
    name: call.expression.name.text,
    receiver: expressionRoot(call.expression.expression),
  }
}

function staticText(node) {
  if (ts.isStringLiteralLike(node)) return node.text
  if (ts.isTemplateExpression(node)) {
    return [
      node.head.text,
      ...node.templateSpans.map(span => span.literal.text),
    ].join('')
  }
  return ''
}

function addNode(state, sourceFile, file, id, layer, label, detail, node) {
  const current = state.nodes.get(id) || {
    id,
    layer,
    label,
    detail,
    evidence: [],
  }
  if (node) mergeEvidence(current.evidence, [evidence(sourceFile, node, file)])
  state.nodes.set(id, current)
}

function addEdge(state, source, target, kind, label, weight, sourceFile, file, node) {
  const key = `${source}\0${target}\0${kind}`
  const current = state.edges.get(key) || {
    source,
    target,
    kind,
    label,
    weight: 0,
    evidence: [],
  }
  current.weight += weight
  if (!current.label && label) current.label = label
  if (sourceFile && node) mergeEvidence(current.evidence, [evidence(sourceFile, node, file)])
  state.edges.set(key, current)
}

function parseSources(sources) {
  for (const file of Object.keys(sources)) {
    if (path.isAbsolute(file)) throw new Error(`TypeScript source key must be relative: ${file}`)
  }
  return new Map(Object.entries(sources).map(([file, text]) => {
    const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
    return [file, ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind)]
  }))
}

function importedBindings(sourceFile) {
  const namespaces = new Set()
  const named = new Set()
  for (const statement of sourceFile.statements) {
    if (!ts.isImportDeclaration(statement) || !statement.importClause) continue
    const clause = statement.importClause
    const moduleName = ts.isStringLiteral(statement.moduleSpecifier)
      ? statement.moduleSpecifier.text
      : ''
    if (!moduleName.includes('/api/')) continue
    if (clause.namedBindings && ts.isNamespaceImport(clause.namedBindings)) {
      namespaces.add(clause.namedBindings.name.text)
    }
    if (clause.namedBindings && ts.isNamedImports(clause.namedBindings)) {
      for (const element of clause.namedBindings.elements) {
        named.add(element.name.text)
        named.add(element.propertyName?.text || element.name.text)
      }
    }
  }
  return { namespaces, named }
}

function importedNamespacesFrom(sourceFile, pathFragment) {
  const namespaces = new Set()
  for (const statement of sourceFile.statements) {
    if (!ts.isImportDeclaration(statement) || !statement.importClause) continue
    const moduleName = ts.isStringLiteral(statement.moduleSpecifier)
      ? statement.moduleSpecifier.text
      : ''
    if (!moduleName.includes(pathFragment)) continue
    const bindings = statement.importClause.namedBindings
    if (bindings && ts.isNamespaceImport(bindings)) namespaces.add(bindings.name.text)
    if (bindings && ts.isNamedImports(bindings)) {
      for (const element of bindings.elements) namespaces.add(element.name.text)
    }
  }
  return namespaces
}

function apiCallAllowed(reference, sourceFile, apiBodies) {
  if (!reference || !apiBodies.has(reference.name)) return false
  if (reference.receiver === 'bare') {
    return apiBodies.get(reference.name).sourceFile === sourceFile
      || importedBindings(sourceFile).named.has(reference.name)
  }
  return importedBindings(sourceFile).namespaces.has(reference.receiver)
}

function storeCallAllowed(reference, sourceFile) {
  return Boolean(
    reference
    && (
      (reference.receiver === 'get' && sourceFile.fileName === 'ui/src/stores/useStore.ts')
      || (
        reference.receiver === 'useStore'
        && (
          sourceFile.fileName === 'ui/src/stores/useStore.ts'
          || importedNamespacesFrom(sourceFile, '/stores/').has('useStore')
        )
      )
    ),
  )
}

function requiredFunction(sourceFiles, file, name) {
  const sourceFile = sourceFiles.get(file)
  const functionNode = sourceFile && functionLikeForName(sourceFile, name)
  if (!sourceFile || !functionNode) {
    throw new Error(`Missing required TypeScript function ${name} in ${file}`)
  }
  return { sourceFile, functionNode }
}

function requiredExportedFunction(sourceFiles, file, name) {
  const sourceFile = sourceFiles.get(file)
  if (!sourceFile) throw new Error(`Missing required TypeScript source ${file}`)
  const candidates = []
  for (const statement of sourceFile.statements) {
    if (ts.isFunctionDeclaration(statement)
      && declarationName(statement) === name
      && statement.body
      && statement.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.ExportKeyword)) {
      candidates.push(statement)
    }
    if (ts.isVariableStatement(statement)
      && statement.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.ExportKeyword)) {
      for (const declaration of statement.declarationList.declarations) {
        if (nameText(declaration.name) !== name || !declaration.initializer) continue
        if (isFunctionLike(declaration.initializer) && declaration.initializer.body) {
          candidates.push(declaration.initializer)
        }
      }
    }
  }
  if (candidates.length === 0) {
    throw new Error(`Missing required exported TypeScript function ${name} in ${file}`)
  }
  if (candidates.length > 1) {
    throw new Error(`Ambiguous required exported TypeScript function ${name} in ${file}`)
  }
  return { sourceFile, functionNode: candidates[0] }
}

function addApiNodes(state, sourceFiles) {
  const apiBodies = new Map()
  for (const name of API_FUNCTIONS) {
    const file = API_FILE_BY_FUNCTION[name]
    const found = requiredFunction(sourceFiles, file, name)
    apiBodies.set(name, { file, ...found })
    addNode(state, found.sourceFile, file, `api.${name}`, 'api', `${name}()`, file, found.functionNode)
  }

  for (const [name, item] of apiBodies) {
    visitAll(item.functionNode.body, node => {
      if (!ts.isCallExpression(node)) return
      const reference = callReference(node)
      if (!reference) return
      const called = reference.name
      if (API_FUNCTIONS.includes(called)
        && called !== name
        && apiCallAllowed(reference, item.sourceFile, apiBodies)) {
        addEdge(
          state,
          `api.${name}`,
          `api.${called}`,
          'call',
          '',
          1,
          item.sourceFile,
          item.file,
          node,
        )
      }
      if (called !== 'fetch' || reference.receiver !== 'bare') return
      const literal = node.arguments[0] && staticText(node.arguments[0])
      if (!literal) return
      for (const [apiName, route] of Object.entries(API_ROUTE_LITERALS)) {
        if (!literal.includes(route)) continue
        const routeByApi = {
          adoptAudio: 'route.adopt_audio',
          uploadAudio: 'route.upload_audio',
          trimAudio: 'route.trim_uploaded_audio',
          startAudioAnalysisJob: 'route.start_audio_analysis_job',
          getFileUrl: 'route.serve_file',
        }
        const target = routeByApi[apiName]
        if (target) {
          addEdge(state, `api.${name}`, target, 'http', name === 'getFileUrl' ? 'GET' : 'POST', 1, item.sourceFile, item.file, node)
        }
      }
    })
    if (name === 'getFileUrl') {
      visitAll(item.functionNode.body, node => {
        if (!ts.isTemplateExpression(node) && !ts.isStringLiteralLike(node)) return
        const literal = staticText(node)
        if (!literal.includes(API_ROUTE_LITERALS.getFileUrl)) return
        addEdge(
          state,
          'api.getFileUrl',
          'route.serve_file',
          'url',
          'produces URL for',
          1,
          item.sourceFile,
          item.file,
          node,
        )
      })
    }
  }
  return apiBodies
}

function addStoreNodes(state, sourceFiles, apiBodies) {
  const foundActions = new Map()
  const storeFile = 'ui/src/stores/useStore.ts'
  for (const action of STORE_ACTIONS) {
    const found = requiredFunction(sourceFiles, storeFile, action)
    foundActions.set(action, found)
    addNode(state, found.sourceFile, storeFile, `store.${action}`, 'store', `${action}()`, storeFile, found.functionNode)
  }
  addNode(state, sourceFiles.get(storeFile), storeFile, 'store.slice', 'store', 'directorSlice.ts', 'directorAudioName / directorAudioPath / directorAnalysis', null)

  for (const [action, item] of foundActions) {
    visitAll(item.functionNode.body, node => {
      if (ts.isCallExpression(node)) {
        const reference = callReference(node)
        const called = reference?.name
        if (called && apiCallAllowed(reference, item.sourceFile, apiBodies)) {
          addEdge(state, `store.${action}`, `api.${called}`, 'call', '', 1, item.sourceFile, storeFile, node)
        }
        if (called && STORE_ACTIONS.includes(called) && storeCallAllowed(reference, item.sourceFile) && called !== action) {
          addEdge(state, `store.${action}`, `store.${called}`, 'call', '', 1, item.sourceFile, storeFile, node)
        }
      }
      if (ts.isPropertyAssignment(node)) {
        const name = declarationName(node)
        if (name === 'directorAudioName' || name === 'directorAnalysis') {
          addEdge(state, `store.${action}`, 'store.slice', 'write', name, 0, item.sourceFile, storeFile, node)
        }
      }
    })
  }
  return foundActions
}

function addUiNodes(state, sourceFiles, storeActions, apiBodies, controller) {
  const controllerFile = UI_FILES['ctrl.story_production_controller'][0]
  addNode(
    state,
    controller.sourceFile,
    controllerFile,
    'ctrl.story_production_controller',
    'controller',
    'storyProductionController.ts',
    controllerFile,
    controller.functionNode,
  )
  for (const [id, [file, layer]] of Object.entries(UI_FILES)) {
    const sourceFile = sourceFiles.get(file)
    if (!sourceFile) throw new Error(`Missing required TypeScript source ${file}`)
    addNode(state, sourceFile, file, id, layer, path.basename(file), file, null)
    visitAll(sourceFile, node => {
      if (ts.isCallExpression(node)) {
        const reference = callReference(node)
        const called = reference?.name
        if (called && storeActions.has(called) && storeCallAllowed(reference, sourceFile)) {
          addEdge(state, id, `store.${called}`, 'call', '', 1, sourceFile, file, node)
        }
        if (called && apiCallAllowed(reference, sourceFile, apiBodies)) {
          addEdge(state, id, `api.${called}`, 'call', '', 1, sourceFile, file, node)
        }
        if (called === CONTROLLER_ENTRY && id !== 'ctrl.story_production_controller') {
          addEdge(state, id, 'ctrl.story_production_controller', 'call', '', 1, sourceFile, file, node)
        }
      }
      if (ts.isPropertyAccessExpression(node)) {
        const name = node.name.text
        if (storeActions.has(name) && !ts.isCallExpression(node.parent)) {
          addEdge(state, id, `store.${name}`, 'reference', '', 0, sourceFile, file, node)
        }
        if (name === 'directorAudioName') {
          addEdge(state, id, 'store.slice', 'read', name, 0, sourceFile, file, node)
        }
      }
    })
  }
}

function validateSourceDiagnostics(sourceFiles, warnings) {
  for (const [file, sourceFile] of sourceFiles) {
    if (sourceFile.parseDiagnostics.length > 0) {
      throw new Error(`TypeScript parser reported syntax diagnostics in ${normalizeFile(file)}`)
    }
  }
}

export function extractTypeScriptGraphFromSources(sources, options = {}) {
  const sourceFiles = parseSources(sources)
  const state = { nodes: new Map(), edges: new Map() }
  const warnings = []
  validateSourceDiagnostics(sourceFiles, warnings)
  const apiBodies = addApiNodes(state, sourceFiles)
  const storeActions = addStoreNodes(state, sourceFiles, apiBodies)
  const controllerFile = UI_FILES['ctrl.story_production_controller'][0]
  const controller = requiredExportedFunction(sourceFiles, controllerFile, CONTROLLER_ENTRY)
  addUiNodes(state, sourceFiles, storeActions, apiBodies, controller)
  const nodes = [...state.nodes.values()].sort((left, right) => left.id.localeCompare(right.id))
  const edges = [...state.edges.values()].sort((left, right) => (
    left.source.localeCompare(right.source)
    || left.target.localeCompare(right.target)
    || left.kind.localeCompare(right.kind)
  ))
  return {
    nodes,
    edges,
    limitations: [...LIMITATIONS],
    warnings: [...new Set([...(options.warnings || []), ...warnings])],
  }
}

export function extractTypeScriptGraph({ root = defaultRoot(), files = TS_SCOPE_FILES } = {}) {
  const sources = {}
  const missing = []
  for (const file of files) {
    const absolute = path.join(root, file)
    if (!fs.existsSync(absolute)) {
      missing.push(file)
      continue
    }
    sources[file] = fs.readFileSync(absolute, 'utf8')
  }
  if (missing.length) throw new Error(`Missing required TypeScript source(s): ${missing.join(', ')}`)
  return extractTypeScriptGraphFromSources(sources)
}

function defaultRoot() {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
}

function parseRoot(argv) {
  const index = argv.indexOf('--root')
  return index >= 0 && argv[index + 1] ? path.resolve(argv[index + 1]) : defaultRoot()
}

function runCli() {
  try {
    process.stdout.write(`${JSON.stringify(extractTypeScriptGraph({ root: parseRoot(process.argv.slice(2)) }), null, 2)}\n`)
  } catch (error) {
    process.stderr.write(`typescript architecture graph: ${error instanceof Error ? error.message : String(error)}\n`)
    process.exitCode = 2
  }
}

const currentFile = path.resolve(fileURLToPath(import.meta.url))
if (process.argv[1] && path.resolve(process.argv[1]) === currentFile) runCli()
