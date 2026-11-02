import json, genanki, os

mapping=json.load(open('/tmp/scratchpad/mapping.json'))
base="/Volumes/Ayaneru/Languages/K-chat/output/phrases"

model = genanki.Model(
    1607392319,
    'K-Chat Phrase',
    fields=[
        {'name': 'Speaker'},
        {'name': 'Text'},
        {'name': 'Audio'},
    ],
    templates=[
        {
            'name': 'Listen',
            'qfmt': '{{Audio}}<br>Who/what is said?',
            'afmt': '{{FrontSide}}<hr id=answer>{{Speaker}}<br>{{Text}}',
        },
    ],
)

deck = genanki.Deck(2059400110, 'GTA VC K-Chat Phrases')

media=[]
for m in mapping:
    if 'audio_abs' not in m: continue
    if not os.path.exists(m['audio_abs']): continue
    rel=m['audio_file']  # relative path
    # Anki media filename should be basename? genanki copies media files by basename. Use basename.
    basename=os.path.basename(m['audio_abs'])
    media.append(m['audio_abs'])
    note = genanki.Note(
        model=model,
        fields=[m['speaker'], m['text'], f"[sound:{basename}]"],
    )
    deck.add_note(note)

genanki.Package(deck, media_files=media).write_to_file("/Volumes/Ayaneru/Languages/K-chat/output/KChat.apkg")
print("deck written, notes", len(deck.notes))
