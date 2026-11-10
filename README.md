# Remake Studio

Remake a video or a script for another language and region, for example English into Spanish for Mexico. It runs on BytePlus ModelArk: Seed LLM, Seedream and Seedance.

Nothing runs on its own. Each step starts only when you click its button (or run its command):

| # | Step | Models | Output |
|---|---|---|---|
| 1 | **Understand.** Breaks the video into scenes, shots with timecodes, characters, locations and the dialogue transcript. A script is broken down the same way. | Seed 2.0 Lite/Mini video understanding (these also hear the audio); the LLM for scripts | `01_understanding.json` |
| 2 | **Localize.** Adapts names, looks, wardrobe, places, props, signage and dialogue for the target language and region, then casts local faces in a separate call that never sees the source actors. IDs and shot order stay the same. | LLM | `02_localized.json` |
| 3 | **Write prompts.** Packs shots into as few clips as the video model allows (up to 30 s on Seedance 2.5, 15 s on 2.0), maps each clip's sheets to `@Image1..N`, then writes every prompt in ONE LLM call: each character sheet, each location plate and each clip (Seedance 2.5 prompt-optimizer skill, dialogue word for word). Every video prompt ends with a strict no-text-overlay rule. | LLM | prompts in `03_sheets.json`, `04_shots.json` |
| 4 | **Sheets.** Generates a 16:9 four-view sheet for each character and an empty plate for each location from its prompt. One card at a time, or all missing/outdated ones. | Image model | `sheets/*.png` |
| 5 | **Video.** Renders clips with the reference images sent inside the request (no TOS, no asset library). One clip at a time, or all missing/outdated ones. | Video model | `clips/*.mp4` |
| 6 | **Assemble.** Normalizes every clip, joins them, and writes a rough subtitle file (a separate file, never burned into the video). | ffmpeg | `final.mp4`, `final.<lang>.srt` |

Every prompt can be read and edited on its card before you generate. Editing a prompt, or regenerating a sheet a clip uses, marks the generated image or clip **outdated**; it is only redone when you click Generate.

Each project is a folder, `projects/<id>/`, holding plain JSON and media. You can review and edit any stage's JSON in the UI before running the next stage. 

## Models

Each project has its own models, chosen when you create it or later under **Models & output**:

- **Video understanding:** Seed 2.0 Mini, Lite, Pro or 2.1 Turbo. Only Mini and Lite hear the dialogue.
- **LLM:** Seed 2.1 Turbo, 2.0 Pro, 2.0 Lite or 2.0 Mini. Used for localizing, the sheet prompts and the shot prompts.
- **Image:** Seedream 5.0 Pro or 5.0 Flash.
- **Video:** Seedance 2.5 (up to 30 s), 2.0, 2.0 fast or 2.0 mini (up to 15 s). Also set the resolution and aspect ratio here.
- **Clip packing:** either fill each generation up to the model's maximum length (the default), or also split at every scene change. You can lower the maximum seconds per generation.

When you change the video model or the clip settings, the clips are regrouped the next time you write prompts, as long as no clip has been rendered yet.

## Setup

Requires Python 3.9 or newer. Run the commands from the `remake_studio` folder.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill in your credentials
```

Fill in `.env` with `ARK_API_KEY`. That is the only key the app needs. You also need ffmpeg (`brew install ffmpeg`); if it isn't installed, the bundled `imageio-ffmpeg` binary is used.

## Run

With the virtualenv active:

```bash
python -m remake serve --port 8100      # web UI on http://127.0.0.1:8100
```

```bash
python -m remake new --video in.mp4 --language Spanish --region Mexico --title "My remake"
python -m remake run <id> --from understand        # one step per command
python -m remake run <id> --from localize
python -m remake run <id> --from prompts           # writes every prompt in one call
python -m remake run <id> --from sheets            # or: --from sheets --only C1,L2
python -m remake run <id> --from shots             # renders video; or: --from shots --only CLIP02
python -m remake run <id> --from assemble
python -m remake status <id>
```

Nothing is generated unless you click its button or run its step. `--until <step>` runs several steps in a row.

`setup.sh` and `remake.sh` are optional shortcuts for the same commands. `./setup.sh` runs the setup steps above. `./remake.sh <args>` runs `python -m remake <args>` with `.venv/bin/python`, from the project folder, so you don't need to activate the virtualenv first.

## Layout

```text
remake/
  engine/      ModelArk calls: LLM JSON, Seedream, Seedance, video understanding, ffmpeg
    skills/    Seedance 2.5 prompt-optimizer skill used when writing shot prompts
  stages/      understand · localize · prompts · sheets · shots · assemble
  pipeline.py  runs stages, records status, applies the project's model choice
  server.py    web UI backend          static/index.html  web UI
projects/      one folder per remake   cache/  scratch downloads
```

## Notes

- Packing never splits a shot. A generation that is shorter than 4 s is padded to 4 s.
- The `.srt` spreads each clip's lines evenly across the clip. Treat it as a starting point and retime it.
