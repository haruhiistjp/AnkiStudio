import json
A=json.load(open('/tmp/scratchpad/align2.json'))
END_OF_AUDIO=6239.68
anchor=[o['coverage']>=0.2 and o['start'] is not None for o in A]
i=0
n=len(A)
while i<n:
    if anchor[i]:
        i+=1; continue
    j=i
    while j<n and not anchor[j]: j+=1
    # gap between previous anchor end and next anchor start
    gs = A[i-1]['end'] if i>0 else 0.0
    ge = A[j]['start'] if j<n else END_OF_AUDIO
    words=[max(1,len(A[k]['text'].split())) for k in range(i,j)]
    tot=sum(words)
    t=gs
    for k,wc in zip(range(i,j),words):
        dur=(ge-gs)*wc/tot
        A[k]['start']=t; A[k]['end']=t+dur; A[k]['filled']=True
        t+=dur
    i=j
PAD_L,PAD_R=0.4,0.6
for i,o in enumerate(A):
    prev_end=A[i-1]['end'] if i>0 else 0.0
    o['cut_start']=max(prev_end,o['start']-PAD_L)
    if i>0 and o['coverage']<0.6 and o['start']-prev_end>2.0:
        o['cut_start']=prev_end+0.05
        o['start_fixed']=True
    if i+1<len(A):
        o['cut_end']=max(o['end']+0.4, min(A[i+1]['start']-0.05, o['end']+6.0))
    else:
        o['cut_end']=o['end']+2.0
json.dump(A, open('/tmp/scratchpad/bounds.json','w'), indent=2)
d=[o['cut_end']-o['cut_start'] for o in A]
print("zero/short(<0.3s):", sum(1 for x in d if x<0.3), " min/avg/max", round(min(d),2), round(sum(d)/len(d),2), round(max(d),2))
