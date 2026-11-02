import json, re, difflib

def norm(s):
    s=s.lower()
    s=re.sub(r'[^a-z0-9 ]',' ',s)
    s=re.sub(r'\s+',' ',s).strip()
    return s

wh=json.load(open('/Volumes/Ayaneru/Languages/K-chat/work/whisper_out/Grand Theft Auto Vice City - K-Chat - PC.json'))
segs=wh['segments']
W=[norm(s['text']) for s in segs]
U=json.load(open('/tmp/scratchpad/utterances.json'))
utt_texts=[norm(u['text']) for u in U]

mapping=[]
i=0
N=len(segs)
M=len(U)
for j in range(M):
    target=utt_texts[j]
    # start at i
    if i>=N:
        # no more segs; append dummy
        mapping.append({"utterance_index":j,"speaker":U[j]['speaker'],"text":U[j]['text'],"start":None,"end":None,"seg_start":i,"seg_end":i})
        continue
    # accumulate
    best_sim=0
    best_end=i
    cur=''
    # try up to 10 segs
    for k in range(i, min(i+12, N)):
        cur = (cur+' '+W[k]).strip()
        sim=difflib.SequenceMatcher(None, cur, target).ratio()
        if sim>best_sim:
            best_sim=sim; best_end=k+1
        # stop if sim high and next would reduce? We'll just take max over window
    if best_end==i:
        best_end=i+1
    a=i; b=best_end
    mapping.append({
        "utterance_index": j,
        "speaker": U[j]['speaker'],
        "text": U[j]['text'],
        "start": segs[a]['start'],
        "end": segs[b-1]['end'],
        "seg_start": a,
        "seg_end": b,
        "sim": best_sim,
        "concat": ' '.join(W[a:b])
    })
    i=b

json.dump(mapping, open('/tmp/scratchpad/mapping.json','w'), indent=2)
print("mapped", len(mapping), "final i", i, "of", N)
# show sims distribution
sims=[m.get('sim',0) for m in mapping if 'sim' in m]
print("avg sim", sum(sims)/len(sims))
print("min sim", min(sims))
# print low sim examples
low=[m for m in mapping if m.get('sim',0)<0.5]
print("low count", len(low))
for m in low[:10]:
    print(round(m['sim'],2), m['speaker'], '|', m['text'][:50], '=>', m['concat'][:50])
