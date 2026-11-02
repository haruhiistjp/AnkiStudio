import json
A=json.load(open('/tmp/scratchpad/align2.json'))
# fill unmatched using neighbours
for i,o in enumerate(A):
    if o['start'] is None:
        prev_end=next((A[j]['end'] for j in range(i-1,-1,-1) if A[j]['end'] is not None), 0.0)
        next_start=next((A[j]['start'] for j in range(i+1,len(A)) if A[j]['start'] is not None), None)
        o['start']=prev_end
        o['end']=next_start if next_start is not None else prev_end+2.0
        o['filled']=True
# monotonic check
bad=0
for i in range(1,len(A)):
    if A[i]['start']+1e-6 < A[i-1]['start']:
        bad+=1
print("non-monotonic starts:", bad)
# padding: start before, end after, without overlapping neighbours
PAD_L, PAD_R = 0.35, 0.5
for i,o in enumerate(A):
    prev_end = A[i-1]['end'] if i>0 else 0.0
    next_start = A[i+1]['start'] if i+1<len(A) else o['end']+PAD_R
    o['cut_start']=max(prev_end, o['start']-PAD_L) if i>0 else max(0.0,o['start']-PAD_L)
    o['cut_end']=max(o['end'], min(next_start, o['end']+PAD_R))
json.dump(A, open('/tmp/scratchpad/bounds.json','w'), indent=2)
d=[o['cut_end']-o['cut_start'] for o in A]
print("durations min/avg/max", round(min(d),2), round(sum(d)/len(d),2), round(max(d),2))
