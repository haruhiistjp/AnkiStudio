# Quick Start

This guide gets you from zero to browsing an Anki deck project in about 5 minutes. No programming experience needed — just copy-paste the commands.

## What you'll need

- A Mac or Linux computer
- Internet connection (for the one-time download, about 100 MB)

---

## Step 1: Install the tools (one time only)

Open **Terminal** (Mac: press `Cmd+Space`, type "Terminal", press Enter) and paste this:

```bash
# Install uv (a Python installer — takes ~10 seconds)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Close and reopen Terminal, then verify:
uv --version
```

If you see a version number like `uv 0.x.x`, you're good.

> **Don't have Python?** That's fine — `uv` installs it automatically in the next step.

---

## Step 2: Download and set up AnkiStudio

Still in Terminal:

```bash
# Download the app
git clone https://github.com/haruhiistjp/AnkiStudio.git
cd AnkiStudio

# Install everything (takes ~1 minute)
uv venv && uv pip install -e ".[jp]"
```

> **What's `[jp]`?** It installs the Japanese text analyzer. Skip it if you're working with another language.

---

## Step 3: Start the app

```bash
ankistudio serve
```

Your browser doesn't open automatically, so go to:

**http://127.0.0.1:8796**

You should see the AnkiStudio interface. To stop the app later, press `Ctrl+C` in Terminal.

---

## Step 4: Open a project

If someone shared a `.aproj` file with you (like `CureDolly.aproj`):

1. Put the file in the `AnkiStudio/data/projects/` folder
2. In the app, click **Projects** in the left sidebar
3. Click **Open** next to the project name

You'll see all the grammar points, sentences, and the deck layout.

---

## What to do next

### Browse sentences
Click **Card browser** in the sidebar. You'll see every sentence from every source. Click any row to see it as a flashcard (with audio and screenshot if available).

### Review a batch
Click **Batch review**. Pick a grammar point, set your filters, and hit **Build pool**. Then use your keyboard:

| Key | Action |
|---|---|
| `Space` | replay audio |
| `A` or `→` | approve (adds to the deck) |
| `X` | reject (for this grammar point only) |
| `S` or `←` | skip |
| `Z` | undo last decision |
| `M` | move to a different grammar point |

### See the deck
Click **Deck** to see all grammar points as blocks. Filled blocks show their cards; empty ones say "empty". Each block has a **+ Fill from pool** button.

### Export to Anki
Click **Export deck**, pick what to include, and hit **Export deck (.apkg)**. Import the resulting file into Anki like any other deck.

---

## Troubleshooting

**"command not found: ankistudio"**
Make sure you're in the AnkiStudio folder and ran `uv pip install -e ".[jp]"`.

**"Port 8796 already in use"**
Another AnkiStudio is running. Close it first (`Ctrl+C` in its Terminal), or start on a different port: `ankistudio serve --port 8797`.

**Audio doesn't play**
The project file (.aproj) contains text and references, not the actual audio files. Audio works when the source Anki decks (.apkg) are on the same computer. Ask whoever shared the project to also share the source decks, or place them in a folder and import them via **Sources**.

**Something else?**
[Open an issue on GitHub](https://github.com/haruhiistjp/AnkiStudio/issues) — describe what you did and what happened.
