import json, genanki, os
OUT="/Volumes/Ayaneru/Languages/K-chat/output"
M=json.load(open(os.path.join(OUT,"manifest.json")))
model=genanki.Model(1607392319,'K-Chat Phrase',
    fields=[{'name':'Speaker'},{'name':'Text'},{'name':'Audio'}],
    templates=[{'name':'Listen','qfmt':'{{Audio}}<br>Who is speaking?','afmt':'{{FrontSide}}<hr id=answer>{{Speaker}}<br>{{Text}}'}])
deck=genanki.Deck(2059400110,'GTA VC K-Chat Phrases')
media=[]
for m in M:
    media.append(m['abs'])
    deck.add_note(genanki.Note(model=model,fields=[m['speaker'],m['text'],f"[sound:{os.path.basename(m['abs'])}]"]))
genanki.Package(deck,media_files=media).write_to_file(os.path.join(OUT,"KChat.apkg"))
print("notes", len(deck.notes))
