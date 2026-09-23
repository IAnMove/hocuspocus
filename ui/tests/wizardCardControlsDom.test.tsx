import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
 HTMLElement: dom.window.HTMLElement, HTMLButtonElement: dom.window.HTMLButtonElement,
 HTMLInputElement: dom.window.HTMLInputElement, HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
 Event: dom.window.Event, CustomEvent: dom.window.CustomEvent, MessageEvent: dom.window.MessageEvent,
 MutationObserver: dom.window.MutationObserver, React, ResizeObserver: class { observe() {} disconnect() {} } })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: () => undefined })
window.matchMedia = () => ({ matches: false }) as MediaQueryList
window.requestAnimationFrame = callback => { callback(0); return 1 }
window.cancelAnimationFrame = () => undefined
Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: class { addEventListener() {} close() {} } })
const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
const { AgentAssistantPanel } = await import('../src/features/agent/AgentAssistantPanel.tsx')
const { useStore } = await import('../src/stores/useStore.ts')
const { cardFromReport } = await import('../src/features/agent/executionCards.ts')
const { setUiLanguage } = await import('../src/i18n/index.ts')
await setUiLanguage('en')
const reply = (x: unknown) => new Response(JSON.stringify(x), {headers:{'content-type':'application/json'}})
function installFetch(extra: (url: string, init?: RequestInit) => Promise<Response>|undefined = () => undefined) {
 const conversations = new Map<string, {revision:number; messages:unknown[]; executions:unknown[]}>()
 globalThis.fetch = async (input, init) => {
  const url = String(input)
  if(url.includes('/api/v1/wizard/workflows')) return reply({version:1,revision:0,workflows:[]})
  if(url.includes('/api/v1/wizard/conversations')) {
   const workspace = new URL(url, 'http://localhost').searchParams.get('workspace') || 'default'
   if(init?.method === 'PUT') {const data=JSON.parse(String(init.body)); conversations.set(workspace, {...data.conversation,revision:(conversations.get(workspace)?.revision||0)+1})}
   return reply(conversations.get(workspace)||{version:1,revision:0,messages:[],executions:[]})
  }
  if(url.includes('/api/v1/outputs')) return reply({outputs:[],total:0})
  if(url.includes('/api/v1/assets')) return reply({assets:[],total:0})
  const result=extra(url,init)
  if(result) return result
  throw new Error(`Unexpected ${init?.method || 'GET'} ${url}`)
 }
}
function seed(workspace:string, report: Partial<import('../src/features/agent/agentContract').AgentExecutionReport> & { state: import('../src/features/agent/agentContract').AgentExecutionState; message: string }) {
 localStorage.clear(); useStore.setState({activeWorkspace:workspace,mediaFilter:'images',generationMode:'video',sidebarMode:'browser',settingsOpen:false,dashboardOpen:false})
 const card = cardFromReport({recoverable:false,...report},'bug-card')
 localStorage.setItem(`hocuspocus-agent-chat-v2:${workspace}`,JSON.stringify([{id:'card-owner',role:'assistant',text:'Original result',createdAt:1,cards:[card]}]))
 return card
}
const failedTask = {id:'unrelated-failed-job',root_id:'unrelated-failed-job',kind:'image',title:'Unrelated render',status:'failed',updated_at:9,created_at:1,resumable:true,recoverable:true,cancelable:false,metadata:{},result_refs:[]}
test('Open destination retains the verified application section',async()=>{
 installFetch();seed('bug-nav',{state:'completed',message:'Opened images',target:{kind:'application_section',id:'images',title:'Images'}})
 render(<AgentAssistantPanel workspace="bug-nav" tasks={[]} onClose={()=>{}} />)
 useStore.setState({mediaFilter:'videos'})
 fireEvent.click(await screen.findByRole('button',{name:'Open section'}))
 await waitFor(()=>assert.equal(useStore.getState().mediaFilter,'images'))
 assert.notEqual(useStore.getState().sidebarMode,'studio')
 cleanup()
})
test('failed cards without a task receipt cannot retry an unrelated queue task',async()=>{
 const requests:string[]=[]
 installFetch((url)=>{ if(url.includes('/api/v1/tasks?')) return Promise.resolve(reply({tasks:[failedTask]})); if(url.includes('/retry?')) {requests.push(url);return Promise.resolve(reply({task:{...failedTask,status:'queued'}}))} })
 seed('bug-retry',{state:'failed',message:'Validation failed before creating a task',recoverable:true})
 render(<AgentAssistantPanel workspace="bug-retry" tasks={[]} onClose={()=>{}} />)
 await screen.findByText('Validation failed before creating a task')
 assert.equal(screen.queryByRole('button',{name:'Retry pending'}),null)
 assert.equal(screen.queryByRole('button',{name:'Resume'}),null)
 assert.deepEqual(requests,[])
 cleanup()
})
test('interrupted canonical tasks expose recovery instead of running cancellation',async()=>{
 installFetch();seed('bug-interrupted',{state:'queued',message:'Queued',taskId:'task-interrupted'})
 const task={...failedTask,id:'task-interrupted',root_id:'task-interrupted',status:'interrupted',message:'Server restarted'}
 render(<AgentAssistantPanel workspace="bug-interrupted" tasks={[task]} onClose={()=>{}} />)
 await screen.findByText('Failed')
 assert.equal(screen.queryByRole('button',{name:'Cancel'}),null)
 assert.ok(screen.getByRole('button',{name:'Retry pending'}))
 assert.ok(screen.getByRole('button',{name:'Resume'}))
 cleanup()
})
test('workspace changes during LLM pause before any queue mutation',async()=>{
 let release!:(response:Response)=>void
 let llmWorkspace=''
 const llm = new Promise<Response>(resolve=>{release=resolve})
 const retries:string[]=[]
 installFetch((url,init)=>{
  if(url.includes('/api/v1/llm/generate')) {llmWorkspace=JSON.parse(String(init?.body)).workspace;return llm}
  if(url.includes('/api/v1/tasks?')) return Promise.resolve(reply({tasks:[failedTask]}))
  if(url.includes('/retry?')) {retries.push(url);return Promise.resolve(reply({task:{...failedTask,status:'queued'}}))}
 })
 localStorage.clear();useStore.setState({activeWorkspace:'workspace-A'})
 const panel=render(<AgentAssistantPanel workspace="workspace-A" tasks={[]} onClose={()=>{}} />)
 const textarea=screen.getByPlaceholderText('Ask HocusPocus for a spell…')
 fireEvent.change(textarea,{target:{value:'Retry the latest failed task in this workspace'}});fireEvent.submit(textarea.closest('form')!)
 await waitFor(()=>assert.equal(llmWorkspace,'workspace-A'))
 useStore.setState({activeWorkspace:'workspace-B'})
 panel.rerender(<AgentAssistantPanel workspace="workspace-B" tasks={[]} onClose={()=>{}} />)
 release(reply({text:JSON.stringify({reply:'Retry',intent:{kind:'action',goal:'Retry latest failed task',question:'',execution:'run'},actions:[{type:'retry_task',task_id:'latest',confirm:true}]})}))
 await waitFor(()=>assert.ok(window.__HOCUSPOCUS_WIZARD_TRACE__?.some(entry => entry.workspace === 'workspace-A' && entry.results)))
 const trace = window.__HOCUSPOCUS_WIZARD_TRACE__!.find(entry => entry.workspace === 'workspace-A' && entry.results)!
 assert.equal((trace.results as { report: { state: string } }[])[0].report.state,'awaiting_input')
 assert.deepEqual(retries,[])
 cleanup()
})

test('discarding an LLM response prevents its late plan from running', async()=>{
 let release!:(response:Response)=>void
 let started=false
 const response=new Promise<Response>(resolve=>{release=resolve})
 const mutations:string[]=[]
 installFetch((url)=>{
  if(url.includes('/api/v1/llm/generate')) {started=true;return response}
  mutations.push(url); return Promise.resolve(reply({tasks:[failedTask]}))
 })
 localStorage.clear();useStore.setState({activeWorkspace:'discarded-turn'})
 render(<AgentAssistantPanel workspace="discarded-turn" tasks={[]} onClose={()=>{}} />)
 const textarea=screen.getByPlaceholderText('Ask HocusPocus for a spell…')
 fireEvent.change(textarea,{target:{value:'Retry the last failed task'}});fireEvent.submit(textarea.closest('form')!)
 await waitFor(()=>assert.equal(started,true))
 fireEvent.click(screen.getByRole('button',{name:'Discard response'}))
 assert.equal((textarea as HTMLTextAreaElement).disabled,false)
 const { act } = await import('@testing-library/react')
 await act(async()=>{
  release(reply({text:JSON.stringify({reply:'Retry',intent:{kind:'action',goal:'Retry',question:'',execution:'run'},actions:[{type:'retry_task',task_id:'latest',confirm:true}]})}))
  await new Promise(resolve=>setTimeout(resolve,0))
 })
 assert.deepEqual(mutations,[])
 assert.ok(screen.getByText(/Response discarded/))
 cleanup()
})

test('card controls validate task identity and preserve section navigation', async()=>{
 const {tabForExecutionTarget,executionCardTaskId}=await import('../src/features/agent/executionCards.ts')
 for(const taskId of [undefined,'','latest','active','current']) {
  assert.equal(executionCardTaskId({taskId}),null)
  assert.equal(cardFromReport({state:'failed',message:'No receipt',recoverable:true,taskId}).controls.retryPending,false)
 }
 assert.equal(tabForExecutionTarget({kind:'application_section',id:'settings',title:'Settings'}),'settings')
 assert.equal(tabForExecutionTarget({kind:'application_section',id:'unknown',title:'Unknown'}),null)
 assert.equal(cardFromReport({state:'failed',message:'Workflow',recoverable:true,taskId:'old-task',target:{kind:'wizard_workflow',id:'workflow-id',title:'Workflow'}}).controls.retryPending,false)
})

test('explicit workspace selection authorizes following actions in its destination', async()=>{
 const requests:string[]=[]
 installFetch((url)=>{
  if(url.includes('/api/v1/workspaces')) return Promise.resolve(reply({active:'chosen-B',workspaces:[{name:'chosen-B'}]}))
  if(url.includes('/api/v1/tasks?')) return Promise.resolve(reply({tasks:[failedTask]}))
  if(url.includes('/retry?')) {requests.push(url);return Promise.resolve(reply({task:{...failedTask,status:'queued'}}))}
 })
 useStore.setState({activeWorkspace:'chosen-B'})
 const {executeAgentActions}=await import('../src/features/agent/agentActions.ts')
 const results=await executeAgentActions([{type:'select_workspace',workspaceName:'chosen-B'},{type:'retry_task',taskId:'latest',confirm:true}],undefined,{workspace:'source-A'})
 assert.equal(results.length,2)
 assert.ok(results.every((result:{ok:boolean})=>result.ok))
 assert.match(requests[0],/workspace=chosen-B/)
})

test('workflow controls use workflow identity without falling back to unrelated tasks', async()=>{
 const {defaultWizardWorkflowRuntime:runtime}=await import('../src/features/agent/wizardWorkflowRuntime.ts')
 const {executeWizardCardControl,wizardCardControls}=await import('../src/features/agent/wizardCardActions.ts')
 const original={get:runtime.get,cancel:runtime.cancel,resume:runtime.resume}
 const calls:string[]=[]
 const workflow={workflowId:'workflow-without-task',workspace:'workflow-space',executorOwner:'',state:'failed',steps:[],currentStep:0}
 runtime.get=()=>workflow
 runtime.cancel=async(id:string)=>{calls.push(`cancel:${id}`);return workflow}
 runtime.resume=async(id:string)=>{calls.push(`resume:${id}`);return workflow}
 const card=cardFromReport({state:'failed',message:'Needs recovery',recoverable:true,target:{kind:'wizard_workflow',id:workflow.workflowId,title:'Workflow'}})
 const requests:string[]=[]
 useStore.setState({activeWorkspace:'workflow-space'})
 installFetch(url=>{requests.push(url);return Promise.resolve(reply({tasks:[failedTask]}))})
 try {
  assert.equal(wizardCardControls(card,'workflow-space').resume,true)
  await executeWizardCardControl(card,'resume','workflow-space')
  workflow.state='waiting'
  assert.equal(wizardCardControls(card,'workflow-space').cancel,true)
  await executeWizardCardControl(card,'cancel','workflow-space')
  await assert.rejects(executeWizardCardControl(card,'retry','wrong-workspace'),/workspace changed/)
  workflow.executorOwner='server'
  assert.equal(wizardCardControls(card,'workflow-space').resume,false)
  await executeWizardCardControl(card,'retry','workflow-space')
  assert.deepEqual(calls,['resume:workflow-without-task','cancel:workflow-without-task'])
  assert.deepEqual(requests,[])
 } finally {Object.assign(runtime,original)}
})
