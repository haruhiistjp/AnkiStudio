import json, re, difflib

def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())

wh=json.load(open('/Volumes/Ayaneru/Languages/K-chat/work/whisper_out/Grand Theft Auto Vice City - K-Chat - PC.json'))
wwords=[]
for s in wh['segments']:
    for w in s['words']:
        t=norm(w['word'])
        if t: wwords.append((t, w['start'], w['end']))

U=json.load(open('/tmp/scratchpad/utterances.json'))
START=506
order=list(range(START,len(U)))+list(range(0,START))
twords=[]  # (token, utt_index)
for ui in order:
    for tok in U[ui]['text'].split():
        t=norm(tok)
        if t: twords.append((t, ui))

a=[t for t,_ in twords]
b=[t for t,_,_ in wwords]
sm=difflib.SequenceMatcher(None, a, b, autojunk=False)
pairs={}  # transcript word idx -> whisper word idx
for blk in sm.get_matching_blocks():
    for k in range(blk.size):
        pairs[blk.a+k]=blk.b+k
print("matched words", len(pairs), "of transcript", len(a), "whisper", len(b))

# per utterance start/end from matched words
per={}
for ti,(tok,ui) in enumerate(twords):
    if ti in pairs:
        wi=pairs[ti]
        s,e=wwords[wi][1], wwords[wi][2]
        if ui not in per: per[ui]=[s,e,0]
        per[ui][0]=min(per[ui][0],s); per[ui][1]=max(per[ui][1],e); per[ui][2]+=1
out=[]
for ui in order:
    total=len(U[ui]['text'].split())
    if ui in per:
        s,e,n=per[ui]
        cov=n/max(1,sum(1 for t,x in twords if x==ui))
    else:
        s,e,cov=None,None,0.0
    out.append({"utterance_index":ui,"speaker":U[ui]['speaker'],"text":U[ui]['text'],"start":s,"end":e,"coverage":round(cov,2)})
json.dump(out, open('/tmp/scratchpad/align2.json','w'), indent=2)
missing=[o for o in out if o['start'] is None]
print("utterances", len(out), "no match", len(missing))
lowc=[o for o in out if o['start'] is not None and o['coverage']<0.5]
print("coverage<0.5:", len(lowc))
for o in lowc[:8]:
    print(o['coverage'], o['speaker'], '|', o['text'][:60])
