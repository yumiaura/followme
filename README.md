# followme

`followme` is a small CLI that scans Python repositories on GitHub, uses `codecat` with a local **Ollama** model to grade authors, and helps identify experienced Python developers.

This repository exists to help you discover experienced Python developers, learn from how they write code, and grow your own skills by following their work.

## Features

- Scans recent Python repositories from GitHub Search API.
- Supports single-repository mode via `username__reponame`.
- Clones repositories with `--depth 1`.
- Collects Python-file digest and requests:
  - numeric grade (`1.0 .. 10.0`)
  - short comment
  - detailed style profile
- Appends style profiles to `data/code_style/{username}__{reponame}.md`.
- Writes every result to CSV (`data/results.csv` by default).
- If `grade > FOLLOW_Y`, performs:
  - `star` repository
  - `follow` repository owner

## Requirements

- Python 3.11+
- Git CLI installed
- Network access to GitHub
- Ollama running with an installed model (for example `qwen2.5-coder:7b`)

## Quick Install (with install.py, for beginners)

Run from project root:

```bash
python3 install.py
```

What `install.py` does:

- creates `.venv` automatically if missing
- installs dependencies from `requirements.txt`
- creates or updates `.env`
- asks for `OLLAMA_URL` and `OLLAMA_MODEL`
- normalizes Ollama URL (for example `10.16.69.251` -> `http://10.16.69.251:11434`)

After install, run:

```bash
python3 followme.py -l 20
```

## Detailed setup (without install.py)

### 1) Create and activate virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` installs `codecat` directly from GitHub:

```text
git+https://github.com/yumiaura/codecat.git
```

### 3) Create `.env` manually

```bash
cp env.example .env
```

Set in `.env` at least:

- `GITHUB_TOKEN`
- `OLLAMA_URL` (for remote host use `http://<ip>:11434`, example `http://10.16.69.251:11434`)
- `OLLAMA_MODEL` (installed Ollama model, for example `qwen2.5-coder:7b`)
- `FOLLOW_OUTPUT_LANGUAGE` (language for generated `comment` and `code_style`, default `English`)

Then verify or adjust:

- `FOLLOW_Y` (default `7.5`)
- `FOLLOW_SCAN_LIMIT` (default `100`)
- `FOLLOW_LANGUAGE` (default `Python`)
- `FOLLOW_OUTPUT_LANGUAGE` (default `English`)
- `MAX_STARS` (default `100`)
- `FOLLOW_RESULTS_CSV` (default `data/results.csv`)
- `FOLLOW_DRY_RUN` (`true`/`false`)
- `FOLLOW_INFINITE_SLEEP_SECONDS` (default `600`, used by `-i/--infinite` when `-s/--sleep` is omitted)
- `CODECAT_DIR` (optional fallback for local source import)

### 4) Run scanner

```bash
python3 followme.py -l 20
```

## Usage

Run from inside the `followme` directory.

### 1) Batch scan mode

```bash
python3 followme.py -l 20
```

Optional flags:

- `-t` / `--threshold 8.0`
- `--dry-run`
- `-r` / `--repo username__reponame` (single repository mode)
- `-i` / `--infinite` + optional `-s` / `--sleep <seconds>` (repeat forever: fetch up to `-l/--limit` repos each cycle, sleep, repeat)
- Default infinite sleep comes from `.env`: `FOLLOW_INFINITE_SLEEP_SECONDS` (default `600`)

Example:

```bash
python3 followme.py -l 10 -t 8.2 --dry-run
```

Infinite mode example (100 repos per cycle from `.env` / defaults, sleep 300s):

```bash
python3 followme.py -i -s 300
```

### 2) Single repository mode

Format: `username__reponame`

```bash
python3 followme.py -r yumiaura__followme
```

Dry run example:

```bash
python3 followme.py -r yumiaura__followme --dry-run
```

## Output

- CSV report: `data/results.csv`
- Style profiles: `data/code_style/*.md`
- Temporary clone workspace: `data/repo` (deleted after each repository)

## Grade scale

`followme` requests strict grading anchors from `codecat`:

- `1.0` = junior
- `5.0` = middle
- `9.0` = senior

Returned grade is clamped to `1.0 .. 10.0`.

## Troubleshooting

- `Bad credentials (401)`:
  - verify `GITHUB_TOKEN`
  - ensure token has permissions for follow and starring.
- `codecat runtime is not importable`:
  - run `pip install -r requirements.txt`
  - or set `CODECAT_DIR` to local codecat source.

