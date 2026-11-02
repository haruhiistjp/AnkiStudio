import json, re, difflib

def norm(s):
    s=s.lower(); s=re.sub(r'[^a-z0-9 ]',' ',s); s=re.sub(r'\s+',' ',s).strip(); return s

wh=json.load(open('/Volumes/Ayaneru/Languages/K-chat/work/whisper_out/Grand Theft Auto Vice City - K-Chat - PC.json'))
segs=wh['segments']; W=[norm(s['text']) for s in segs]
U=json.load(open('/tmp/scratchpad/utterances.json')); UT=[norm(u['text']) for u in U]
M=len(U); N=len(segs)

def greedy_align(start_u, num_u, start_i):
    # returns total sim and end i
    i=start_i; total=0
    for t in range(num_u):
        uidx=(start_u+t)%M
        target=UT[uidx]
        best_sim=0; best_end=i
        cur=''
        for k in range(i, min(i+12, N)):
            cur=(cur+' '+W[k]).strip()
            sim=difflib.SequenceMatcher(None, cur, target).ratio()
            if sim>best_sim:
                best_sim=sim; best_end=k+1
        if best_end==i: best_end=min(i+1,N)
        total+=best_sim
        i=best_end
    return total, i

best=None
for r in range(M):
    sim,end=greedy_align(r, 20, 0)
    if best is None or sim>best[0]:
        best=(sim,r,end)
print("best r", best[1], "sim", best[0], "end", best[2])
# show utterance at r
print("start utt:", U[best[1]]['speaker'], U[best[1]]['text'][:80])
