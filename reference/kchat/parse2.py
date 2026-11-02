import re, json
path="/Volumes/Ayaneru/Languages/K-chat/transcript.md"
lines=open(path).read().splitlines()
start=0
for i,l in enumerate(lines):
    if '(5) Script' in l:
        start=i; break
lines=lines[start:]
# stop before section 6
end=len(lines)
for i,l in enumerate(lines):
    if "Links from the Past" in l or "Links to the Past" in l:
        end=i; break
lines=lines[:end]

utterances=[]
cur=None
for l in lines:
    if not l.strip():
        if cur: utterances.append(cur); cur=None
        continue
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
if cur: utterances.append(cur)

# Remove non-dialogue utterances (copyright/notes)
bad={"And here's some more","This script for K-Chat on GTA"}
utterances=[u for u in utterances if u["speaker"] not in bad]
# also drop if text starts with copyright note
utterances=[u for u in utterances if "may not be reproduced" not in u["text"]]

json.dump(utterances, open("/tmp/scratchpad/utterances.json","w"), indent=2)
print("num", len(utterances))
from collections import Counter
print(Counter(u["speaker"] for u in utterances))
