[中文](README.md) · **English**

# vlog-director

**Hundreds of GB of travel footage you'll never edit? Hand it to Claude. It plays director, editor and footage librarian. You just review the cuts.**

A [Claude Code](https://claude.com/claude-code) skill. Give it a folder of raw video and it first "watches" every clip into one row of a searchable table, then edits from that table: a long-form vlog with subtitles, or a magazine-card montage where every cut lands on a bar of the music.

![A montage made with vlog-director](assets/hero.gif)

<sub>From a 1-minute montage of a 6-day trip: 358 clips, 13.7 hours of footage. Shot selection, cards, titles and beat sync were all done by the skill.</sub>

## Quick start

```bash
git clone https://github.com/quangtoanhoang767-ux/vlog-director ~/.claude/skills/vlog-director
```

Open Claude Code and say:

> Turn the footage in D:\trip into a vlog

It asks a few questions (where the footage is, who's in it, long-form or montage) and walks you to a finished video step by step. It installs its own dependencies (Python packages, ffmpeg, open-source fonts).

## Gallery

All from the same montage. Each frame is one shot the skill laid out on its own:

| | |
| --- | --- |
| ![HANOI](assets/card_hanoi.jpg) | ![OVER MY HEAD](assets/card_train.jpg) |
| Card slides in from the side over a zoomed, fogged background | Titles auto-shrink to fit, with an optional Chinese subtitle |
| ![CLEAR WATER](assets/card_clearwater.jpg) | ![RAINBOW TOWER](assets/card_rainbow.jpg) |
| On the music drop: white flash + a 2-bar hero shot | Cards alternate left and right to keep the rhythm |
| ![ICED COFFEE](assets/card_coffee.jpg) | ![FINALLY](assets/card_finally.jpg) |
| Italic serif kicker, heavy sans title | Closing shot, then the frame fades to paper white with a serif end card |

Before cutting anything, it turns all the footage into a table. Left: the frame. Right: its row in the table.

![Reality to data](assets/reality_to_data.jpg)

All 390 segments of the trip laid out by time; brighter means more worth using. You can see at a glance which day was best and which clips are must-haves:

![Overview of 390 segments](assets/overview_390.jpg)

## What it makes

- **Long-form vlog**: a few minutes to 15+, with a story and subtitled dialogue. Music has exactly two fixed levels: low under speech, up when nobody talks. No pumping volume.
- **Montage**: a 1 to 2 minute magazine-card edit. Every cut lands on a bar line. The intro develops out of a white page with a serif title and an optional flight route that lights up one stop every two beats; the outro fades the last shot to white.
- **Footage table**: one row per clip with time, place, people, quotes, how funny, whether it works as an opener, graded S/A/B/C, exported to a spreadsheet. Looking for "that shot" later is just a lookup.
- **Extras**: stills for social posts and covers, a short personal film for each person.

## Install

Pick one. Each ends with the `vlog-director` folder in your Claude Code skills directory:

- **git**: the command in Quick start.
- **ZIP**: Code → Download ZIP on GitHub, unzip into:
  - macOS / Linux: `~/.claude/skills/vlog-director/`
  - Windows: `C:\Users\<you>\.claude\skills\vlog-director\`
- **One project only**: put it in that project's `.claude/skills/vlog-director/`.

## Usage

Getting started:

> Turn the footage in D:\trip into a vlog
>
> Four of us went to Japan for 5 days. Make a long-form cut, around 10 minutes

When reviewing, just say how it feels. No editing vocabulary needed:

> Too long, get it down to 8 minutes
>
> The opening repeats shots from the main part
>
> The music shouldn't be louder than the voices
>
> The BGM keeps getting louder and quieter
>
> Now make a 2-minute montage with music all the way through

Finding shots:

> Where's the shot of the grilled crocodile?
>
> List every clip that could work as an opener

Habits that make a big difference:

- **With lots of footage, run 3 to 5 clips end to end first**, then open it up to everything.
- **Take the "who's who" step seriously.** It crops a frame of each person and asks you to name them. Get that wrong and everything downstream is wrong.
- **Name the shots you want**: "the one where he waves his hat at the beach has to be in." It will find it in the table.

## How it works

The whole method is one line: **build the table first, then cut.**

No model can watch 13 hours of video start to finish, so "watching" is split in two: **listening** (local Whisper transcription with timestamps, plus loudness, since sudden loud spots are usually laughter) and **looking** (a frame every 3 seconds, tiled into contact sheets). Each clip becomes a row in the table. From then on, choosing shots, building the story and finding a line of dialogue are all lookups.

Seven stages. After each one it stops, reports, and waits for your go-ahead:

1. **Prep**: where the footage is, what it is, what you want; checks your machine and estimates time.
2. **Process**: proxies, transcription, contact sheets. The slow part; resumable.
3. **Who's who**: crops a clear frame of each person and asks you to name them.
4. **Build the table**: one graded row per clip, exported to a spreadsheet.
5. **Story plan**: throughline, each person's highlights, the funny bits, callbacks, opening and ending candidates.
6. **Edit**: writes an edit list (the last column of every row is "why this shot"), renders, and spot-checks frames.
7. **Review**: applies your notes; every version gets a new number, nothing is overwritten.

Hard rules:

- **Source footage is read-only.** No script ever writes, changes or deletes anything in it.
- **No making things up.** Transcription mishears and hallucinates; people get misidentified. Anything uncertain is flagged and asked about, and key lines are re-checked before they become subtitles.
- **Music always sits under the voices.**

Details live in [`SKILL.md`](SKILL.md) and [`references/`](references/): table fields, grading, story structure, montage layout, how plain-language feedback maps to edits, and known pitfalls.

## Requirements and limits

- **Claude Code** and **Python 3.10+**.
- **An NVIDIA GPU** (strongly recommended). Transcription runs at about 1/10 of footage length; CPU-only works but is several times slower and slightly less accurate.
- **Disk**: about 10% of the source footage size.
- **Render time** (measured on an RTX-class GPU): a 12-minute vlog takes about 30 minutes the first time, then only changed shots re-render; a 2-minute montage takes about 12 minutes.
- **Music is the weak spot.** Without a song of your own it synthesizes royalty-free music in code (light acoustic guitar for long-form, 140 BPM electronic for montages). Usable, but you can tell it was made, not composed. For better results, use a song you like.
- **Not one-click.** Whether it's good or funny is still your call. Its real strength is memory.

## Privacy

Your footage never leaves your machine, and transcription and rendering run locally. But to "watch" the footage, Claude reads the contact sheets and transcripts, and that content is sent to Claude. Think about that before you start.

The who's-who list and people's names stay in your local working directory and are never written into anything meant to be shared.

## Fonts

System fonts first; anything missing is downloaded from Google Fonts (Noto Sans SC, Noto Serif SC, Archivo Black, Libre Baskerville, Long Cang, Noto Symbols 2), all under the SIL Open Font License and free for commercial use. To use your own fonts, set paths under `fonts` in `project.json`.

## Contributing

Made something with it? Show it off in Issues. Found a bug or a new pitfall? Issues and PRs welcome.

## License

MIT
