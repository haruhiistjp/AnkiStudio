import json, subprocess, os, re, shutil
A=json.load(open('/tmp/scratchpad/bounds.json'))
SRC="/Volumes/Ayaneru/Languages/K-chat/Grand Theft Auto Vice City - K-Chat - PC.mp4"
OUT="/Volumes/Ayaneru/Languages/K-chat/output"
BASE=os.path.join(OUT,"phrases")
if os.path.exists(BASE): shutil.rmtree(BASE)
os.makedirs(BASE)
ALIAS={"Baking":"Backing","BJ Smith":"BJ","Pastor Richards":"Pastor","Doc in background":"Doc","Caller 1":"Caller","Caller 2":"Caller"}
def safe(s):
    s=re.sub(r'[^A-Za-z0-9 _-]','',s).strip()
    return re.sub(r'\s+','_',s)[:40] or "x"
counts={}
manifest=[]
for idx,o in enumerate(A):
    sp=ALIAS.get(o['speaker'],o['speaker'])
    folder=os.path.join(BASE,safe(sp)); os.makedirs(folder,exist_ok=True)
    counts[sp]=counts.get(sp,0)+1
    txt=re.sub(r'[^A-Za-z0-9 ]','',o['text'])[:30].strip().replace(' ','_')
    fname=f"{idx:04d}_{counts[sp]:03d}_{safe(txt)}.mp3"
    out=os.path.join(folder,fname)
    dur=o['cut_end']-o['cut_start']
    subprocess.run(["ffmpeg","-y","-ss",f"{o['cut_start']:.3f}","-i",SRC,"-t",f"{dur:.3f}","-vn","-acodec","libmp3lame","-q:a","4",out],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    manifest.append({"index":idx,"speaker":sp,"text":o['text'],"file":os.path.relpath(out,OUT),"abs":out,"start":round(o['cut_start'],3),"end":round(o['cut_end'],3),"coverage":o['coverage']})
json.dump(manifest,open(os.path.join(OUT,"manifest.json"),"w"),indent=2,ensure_ascii=False)
print("cut", len(manifest))
