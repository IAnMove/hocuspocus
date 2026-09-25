"""Resumable public HocusPocus job transport; all media processing runs in the app."""
import argparse, io, json, pathlib, time, urllib.parse, wave
import requests

p = argparse.ArgumentParser()
for name in ['base-url', 'spec', 'output']:
    p.add_argument('--' + name, required=True)
a = p.parse_args()
out = pathlib.Path(a.output)
records = json.loads(out.read_text()) if out.exists() else {}

def save():
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2))

def request(path, body=None):
    r = requests.request('GET' if body is None else 'POST', a.base_url.rstrip('/') + path,
                         json=body, timeout=(10, 300))
    r.raise_for_status()
    return r.json()

for item in json.loads(pathlib.Path(a.spec).read_text()):
    key = item['id']
    record = records.get(key)
    if record:
        assert record['request'] == item['request'], 'Request changed; use a new job ID'
    else:
        record = {**item, 'job': request(item['endpoint'], item['request'])}
        records[key] = record
        save()
        print('STARTED', key, record['job'], flush=True)
    if record.get('duration') or record.get('complete'):
        continue
    jid = record['job'].get('job_id') or record['job'].get('jobId')
    while True:
        status = request('/api/v1/status/' + jid)
        if status['status'] in ['completed', 'failed', 'cancelled']:
            break
        time.sleep(3)
    record['status'] = status
    save()
    if status['status'] != 'completed':
        raise RuntimeError(str(status))
    files = status.get('output_files', [])
    wavs = [f for f in files if f.endswith('.wav')]
    if wavs:
        filename = wavs[0]
        r = requests.get(a.base_url + '/api/v1/file/' + urllib.parse.quote(filename, safe='') +
                         '?workspace=' + urllib.parse.quote(item['request']['workspace']), timeout=60)
        r.raise_for_status()
        with wave.open(io.BytesIO(r.content)) as w:
            record['duration'] = w.getnframes() / w.getframerate()
        record['filename'] = filename
    record['complete'] = True
    save()
    print('COMPLETED', key, record.get('duration'), files, flush=True)
