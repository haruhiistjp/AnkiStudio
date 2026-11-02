import json, subprocess, os, re, shutil

mapping=json.load(open('/tmp/scratchpad/mapping.json'))
src="/Volumes/Ayaneru/Languages/K-chat/Grand Theft Auto Vice City - K-Chat - PC.mp4"
base="/Volumes/Ayaneru/Languages/K-chat/output/phrases"
if os.path.exists(base): shutil.rmtree(base)
os.makedirs(base)

def safe(s):
    s=re.sub(r'[^A-Za-z0-9 _-]','',s).strip()
    s=re.sub(r'\s+','_',s)
    return s[:40] if s else "x"

# track counts per speaker for unique names
counts={}
for idx,m in enumerate(mapping):
    if m.get('start') is None: continue
    sp=m['speaker']
    folder=os.path.join(base, safe(sp))
    os.makedirs(folder, exist_ok=True)
    counts[sp]=counts.get(sp,0)+1
    n=counts[sp]
    # short text
    txt=re.sub(r'[^A-Za-z0-9 ]','',m['text'])[:30].strip().replace(' ','_')
    fname=f"{idx:04d}_{n:03d}_{safe(txt)}.mp3"
    out=os.path.join(folder, fname)
    # ffmpeg cut
    cmd=["ffmpeg","-y","-ss",str(m['start']),"-to",str(m['end']),"-i",src,"-vn","-acodec","libmp3lame","-q:a","4",out]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    m['audio_file']=os.path.relpath(out, base)
    m['audio_abs']=out

json.dump(mapping, open('/tmp/scratchpad/mapping.json','w'), indent=2)
print("done cuts", len(mapping))
