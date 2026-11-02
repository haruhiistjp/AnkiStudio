import re
path="/Volumes/Ayaneru/Languages/K-chat/transcript.md"
lines=open(path).read().splitlines()
# Find script section start
start=None
for i,l in enumerate(lines):
    if "5 - Script" in l or "Script" in l and i>180:
        start=i; break
print("start", start)
# We'll parse from line ~186 onward
# dialogue pattern: Speaker: text, continuation indented
# skip headers/boxes
utterances=[]
cur=None
for l in lines[186:]:
    if not l.strip():
        if cur: utterances.append(cur); cur=None
        continue
    # skip box lines
    if set(l.strip()) <= set("=_| ") and l.strip() and ("|" in l or "=" in l or "_" in l):
        # but text lines may contain? unlikely
        if re.match(r'^[\s=|_]+$', l):
            if cur: utterances.append(cur); cur=None
            continue
    m=re.match(r'^([A-Za-z][A-Za-z0-9 \'\-\.]*?):\s*(.*)$', l)
    if m and not l.startswith(" "):
        if cur: utterances.append(cur)
        speaker=m.group(1).strip()
        text=m.group(2).strip()
        cur={"speaker":speaker,"text":text}
    else:
        if cur:
            cur["text"] += " " + l.strip()
        else:
            pass
if cur: utterances.append(cur)
print("num utterances", len(utterances))
# show speakers
from collections import Counter
c=Counter(u["speaker"] for u in utterances)
print(c)
# save
import json
json.dump(utterances, open("/tmp/scratchpad/utterances.json","w"), indent=2)
