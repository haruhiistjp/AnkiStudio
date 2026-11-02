import json, subprocess, os, re, shutil
OUT="/Volumes/Ayaneru/Languages/K-chat/output"
SRC="/Volumes/Ayaneru/Languages/K-chat/Grand Theft Auto Vice City - K-Chat - PC.mp4"
M=json.load(open(os.path.join(OUT,"manifest.json")))
runs=[]
for m in M:
    if runs and runs[-1]['section']==m['section'] and runs[-1]['kind']==m['kind']:
        runs[-1]['last']=m['end']
    else:
        runs.append({'section':m['section'],'kind':m['kind'],'first':m['start'],'last':m['end']})
def safe(s): return re.sub(r'\s+',' ',re.sub(r'[^A-Za-z0-9 \'\-]','',s)).strip()
dirs={"Interviews":"Whole Interviews","Commercials":"Whole Commercials"}
for d in dirs.values():
    p=os.path.join(OUT,d)
    if os.path.exists(p): shutil.rmtree(p)
    os.makedirs(p)
counts={}
for i,r in enumerate(runs):
    d=os.path.join(OUT,dirs[r['kind']])
    out=os.path.join(d,f"{i+1:02d} - {safe(r['section'])}.mp3")
    dur=r['last']-r['first']
    subprocess.run(["ffmpeg","-y","-ss",f"{r['first']:.3f}","-i",SRC,"-t",f"{dur:.3f}","-vn","-acodec","libmp3lame","-q:a","4",out],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    counts[r['kind']]=counts.get(r['kind'],0)+1
print(counts)
