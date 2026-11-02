import json, re, difflib

def norm(s):
    s=s.lower(); s=re.sub(r'[^a-z0-9 ]',' ',s); s=re.sub(r'\s+',' ',s).strip(); return s

wh=json.load(open('/Volumes/Ayaneru/Languages/K-chat/work/whisper_out/Grand Theft Auto Vice City - K-Chat - PC.json'))
segs=wh['segments']; W=[norm(s['text']) for s in segs]
U=json.load(open('/tmp/scratchpad/utterances.json')); UT=[norm(u['text']) for u in U]
M=len(U); N=len(segs)

start_r=506
mapping=[]
i=0
cycle=0
uidx=start_r
count=0
max_utterances=2000
while i < N and count < max_utterances:
    target=UT[uidx]
    best_sim=0; best_end=i
    cur=''
    for k in range(i, min(i+12, N)):
        cur=(cur+' '+W[k]).strip()
        sim=difflib.SequenceMatcher(None, cur, target).ratio()
        if sim>best_sim:
            best_sim=sim; best_end=k+1
    if best_end==i:
        best_end=min(i+1,N)
    a=i; b=best_end
    mapping.append({
        "utterance_index": uidx,
        "cycle": cycle,
        "speaker": U[uidx]['speaker'],
        "text": U[uidx]['text'],
        "start": segs[a]['start'],
        "end": segs[b-1]['end'],
        "seg_start": a,
        "seg_end": b,
        "sim": best_sim,
        "concat": ' '.join(W[a:b])
    })
    i=b
    uidx=(uidx+1)%M
    if uidx==start_r:
        cycle+=1
    count+=1

json.dump(mapping, open('/tmp/scratchpad/mapping.json','w'), indent=2)
print("aligned utterances:", len(mapping), "final i", i, "of", N, "cycles", cycle)
sims=[m['sim'] for m in mapping]
print("avg sim", sum(sims)/len(sims), "min", min(sims))
low=[m for m in mapping if m['sim']<0.35]
print("low count", len(low))
for m in low[:15]:
    print(round(m['sim'],2), m['speaker'], '|', m['text'][:40], '=>', m['concat'][:40])
