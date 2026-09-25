"""Generate a specified image batch through HocusPocus's public MiniMax jobs API."""
import argparse,json,pathlib,time,urllib.request,urllib.parse
import requests
def request(base_url,path,method="GET",payload=None):
 r=requests.request(method,base_url.rstrip("/")+path,json=payload,timeout=(10,300));r.raise_for_status();return r.json()
p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--workspace',required=True);p.add_argument('--spec',required=True);p.add_argument('--output-dir',required=True);a=p.parse_args();out=pathlib.Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
items=json.loads(pathlib.Path(a.spec).read_text());jobs=[]
for item in items:
 f=out/(item['id']+'-job.json');body={k:v for k,v in item.items() if k in ['prompt','aspect_ratio','subject_reference']};body['workspace']=a.workspace
 if f.exists():r=json.loads(f.read_text());assert r['request']==body
 else:r={'request':body,'job':request(a.base_url,'/api/v1/comics/generate/minimax/jobs','POST',body)};f.write_text(json.dumps(r,ensure_ascii=False,indent=2))
 jobs.append((item,f,r));print('STARTED',item['id'],r['job'].get('jobId'),flush=True)
while jobs:
 for item,f,r in list(jobs):
  jid=r['job'].get('jobId') or r['job'].get('job_id');s=request(a.base_url,'/api/v1/comics/generate/minimax/jobs/'+jid);r['status']=s;f.write_text(json.dumps(r,ensure_ascii=False,indent=2))
  if s['status']=='completed':
   asset=s['result']['asset'];url=a.base_url+asset['source']+'?'+urllib.parse.urlencode({'workspace':a.workspace});target=out/(item['id']+pathlib.Path(asset['name']).suffix)
   with urllib.request.urlopen(url,timeout=60) as response:target.write_bytes(response.read())
   print('COMPLETED',item['id'],target,flush=True);jobs.remove((item,f,r))
  elif s['status'] in ['failed','cancelled']:raise RuntimeError(item['id']+': '+str(s.get('error') or s.get('message')))
 if jobs:time.sleep(5)
