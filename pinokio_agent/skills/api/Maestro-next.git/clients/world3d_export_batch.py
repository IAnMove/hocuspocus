"""Save and render reviewed shots through HocusPocus's native public World3D API."""
import argparse,json,pathlib,time,urllib.parse
import requests
p=argparse.ArgumentParser()
for x in ['base-url','plan','previews','output-dir','intent-prefix']:p.add_argument('--'+x,required=True)
a=p.parse_args();plan=json.loads(pathlib.Path(a.plan).read_text());out=pathlib.Path(a.output_dir);out.mkdir(parents=True,exist_ok=True);workspace=plan['workspace']
def api(path,body=None):
 for attempt in range(6):
  try:
   r=requests.request('GET' if body is None else 'POST',a.base_url.rstrip('/')+path,json=body,timeout=(10,180));break
  except requests.RequestException:
   if attempt==5 or (body is not None and path!='/api/v1/scenes/world3d/export'):raise
   print('RETRY TRANSIENT',path,flush=True);time.sleep(5)

 if not r.ok: raise RuntimeError(f'{r.status_code}: {r.text[:2000]}')
 return r.json()
for shot in plan['shots']:
 n=shot['number'];stem=f'clip-{n:02}';recfile=out/(stem+'.publication.json')
 if recfile.exists() and (out/(stem+'.mp4')).exists():print('EXISTS',n,flush=True);continue
 savefile=out/(stem+'.scene-publication.json')
 if not savefile.exists():
  body=json.loads((pathlib.Path(a.previews)/f'{n:02}-save-request.json').read_text());body['name']=f"{plan.get('title', 'Video 3D')} {n:02} "+shot['title'];r=api('/api/v1/scenes/world3d',body);savefile.write_text(json.dumps(r,indent=2))
 req={'version':1,'operation':'scenes.world3d.export','intent_id':f'{a.intent_prefix}-{n:02}','input':{'workspace':workspace,'document':shot['document']}}
 req['input']['refs']=[{'slotId':slot['id'],'url':slot['sourceUrl'],'kind':slot['media']} for slot in shot['document']['slots'] if slot.get('sourceUrl','').startswith('/examples/')]
 r=api('/api/v1/scenes/world3d/export',req);(out/(stem+'.admission.json')).write_text(json.dumps({'request':req,'receipt':r},indent=2));print('ADMITTED',n,json.dumps(r),flush=True)
 tid=r.get('task_id') or r.get('taskId') or r.get('task',{}).get('id') or r.get('receipt',{}).get('result',{}).get('task_id');assert tid,r
 started=time.monotonic();prev=None
 while True:
  task=api('/api/v1/tasks/'+urllib.parse.quote(tid)+'?workspace='+urllib.parse.quote(workspace));task=task.get('task',task);(out/(stem+'.task.json')).write_text(json.dumps(task,indent=2))
  state=(task.get('status'),task.get('current'),task.get('total'))
  if state!=prev:print('PROGRESS',n,state,flush=True);prev=state
  if task['status']=='completed':break
  if task['status'] in ['failed','cancelled']:raise RuntimeError(json.dumps(task))
  time.sleep(3)
 saved=task['metadata']['output'];url=urllib.parse.urljoin(a.base_url,saved['url'])+'?workspace='+urllib.parse.quote(workspace)
 r=requests.get(url,timeout=180);r.raise_for_status();(out/(stem+'.mp4')).write_bytes(r.content)
 record={'clip':n,'title':shot['title'],'saved':saved,'bytes':len(r.content),'elapsedSeconds':round(time.monotonic()-started,2),'scene':json.loads(savefile.read_text())};recfile.write_text(json.dumps(record,ensure_ascii=False,indent=2));print('COMPLETED',n,record['elapsedSeconds'],len(r.content),flush=True)
