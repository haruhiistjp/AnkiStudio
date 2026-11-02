import json, re, os, shutil
path="/Volumes/Ayaneru/Languages/K-chat/transcript.md"
lines=open(path).read().splitlines()
start=next(i for i,l in enumerate(lines) if '(5) Script' in l)
end=next(i for i,l in enumerate(lines) if i>start and ('Links from the Past' in l or 'Links to the Past' in l))
lines=lines[start:end]
utts=[]; cur=None; section=None
hdr=re.compile(r'^\|\s+([a-z]{1,2})\) (.+?)\s*\|')
for l in lines:
    h=hdr.match(l)
    if h:
        if cur: utts.append(cur); cur=None
        section=h.group(2).strip()
        continue
    if not l.strip():
        if cur: utts.append(cur); cur=None
        continue
    if re.match(r'^[\s=|_]+$', l):
        if cur: utts.append(cur); cur=None
        continue
    m=re.match(r'^([A-Za-z][A-Za-z0-9 \'\-\.]*?):\s*(.*)$', l)
    if m and not l.startswith(" "):
        if cur: utts.append(cur)
        cur={"speaker":m.group(1).strip(),"text":m.group(2).strip(),"section":section}
    elif cur:
        cur["text"]+=" "+l.strip()
if cur: utts.append(cur)
bad={"And here's some more","This script for K-Chat on GTA"}
utts=[u for u in utts if u["speaker"] not in bad and "may not be reproduced" not in u["text"]]
ref=json.load(open('/tmp/scratchpad/utterances.json'))
assert len(utts)==len(ref), (len(utts),len(ref))
assert all(a['speaker']==b['speaker'] for a,b in zip(utts,ref))
sec_by_utt={i:u['section'] for i,u in enumerate(utts)}
def kind(sec):
    return "Commercials" if sec.startswith("AD") or sec=="Commercial Break" else "Interviews"
B=json.load(open('/tmp/scratchpad/bounds.json'))
OUT="/Volumes/Ayaneru/Languages/K-chat/output"
M=json.load(open(os.path.join(OUT,"manifest.json")))
for folder in ["Commercials","Interviews"]:
    p=os.path.join(OUT,folder)
    if os.path.exists(p): shutil.rmtree(p)
    os.makedirs(p)
counts={"Commercials":0,"Interviews":0}
for i,(b,m) in enumerate(zip(B,M)):
    sec=sec_by_utt[b['utterance_index']]
    k=kind(sec)
    m['section']=sec; m['kind']=k
    shutil.copy2(m['abs'], os.path.join(OUT,k,os.path.basename(m['abs'])))
    counts[k]+=1
json.dump(M,open(os.path.join(OUT,"manifest.json"),"w"),indent=2,ensure_ascii=False)
print(counts)
