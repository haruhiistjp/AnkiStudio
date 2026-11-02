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

# DP: align utterances to contiguous groups of whisper segments
# dp[j][i] = best total similarity covering first j utterances using first i segments
# We'll do iterative DP with backpointers.
M=len(utt_texts)
N=len(segs)
maxk=8
# dp[i][j] maybe memory heavy: (N+1)*(M+1)
NEG=-1e9
# use list of dicts? Let's do 2D arrays
dp=[[NEG]*(N+1) for _ in range(M+1)]
back=[[None]*(N+1) for _ in range(M+1)]
dp[0][0]=0.0
for j in range(1,M+1):
    for i in range(j,N+1):  # need at least j segments
        # try k
        best=NEG; bestk=None
        for k in range(1,maxk+1):
            if i-k < j-1: break
            if dp[j-1][i-k] == NEG: continue
            # concat whisper i-k..i-1
            concat=' '.join(W[i-k:i])
            sim=difflib.SequenceMatcher(None, concat, utt_texts[j-1]).ratio()
            # small bonus for length closeness? ratio enough
            val=dp[j-1][i-k]+sim
            if val>best:
                best=val; bestk=k
        if best>NEG:
            dp[j][i]=best
            back[j][i]=bestk

# find best end i for M utterances
besti=max(range(M,N+1), key=lambda i: dp[M][i])
print("besti", besti, "dp", dp[M][besti])
# backtrack
ranges=[]
i=besti
for j in range(M,0,-1):
    k=back[j][i]
    ranges.append((i-k, i))  # segment indices [start,end)
    i-=k
ranges.reverse()
print("num ranges", len(ranges))
# save mapping
mapping=[]
for idx,(a,b) in enumerate(ranges):
    mapping.append({
        "utterance_index": idx,
        "speaker": U[idx]['speaker'],
        "text": U[idx]['text'],
        "start": segs[a]['start'],
        "end": segs[b-1]['end'],
        "seg_start": a,
        "seg_end": b,
        "sim_concat": ' '.join(W[a:b])
    })
json.dump(mapping, open('/tmp/scratchpad/mapping.json','w'), indent=2)
# print a few
for m in mapping[:5]:
    print(m['speaker'], round(m['start'],2), round(m['end'],2), m['text'][:60])
