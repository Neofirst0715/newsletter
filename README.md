# Volta Newsletter Pipeline

> **TODO before demo:** the line below is a placeholder describing what the
> code actually does -- swap it for your Problem Statement's *What* and
> *Desired Outcome* if you want the judges to see the exact framing you
> pitched.

Automatically collects Atlantic Canada / Halifax startup and Volta
community event listings, drafts a plain-language weekly newsletter from
them, and routes every send through a human review step before anything
actually goes out.

## Architecture

The pipeline is six layers, each with a clear boundary:

| Layer | File | Responsibility |
|---|---|---|
| 1. Collection | `collect.py` (`fetch_events()`) | Scrapes structured event data (title/date/url/source) from Volta's events page and Eventbrite's Halifax tech/startup category page. Pure fact extraction -- no rewriting, no judgment calls. Any source that fails just contributes an empty list instead of crashing. |
| 2. Governance / Dedup | `collect.py` (`dedupe_and_filter()`) | Filters out events already recorded in `state/sent_log.json` by exact key match (event URL, or `title\|date` when there's no URL). Lives in the same file as collection since it's the direct next step on the same data. |
| 3. Generation | `generate.py` (`generate_newsletter()`) | Turns the deduped event list into email copy via a local Ollama model (`qwen2.5:7b`). The system prompt hard-constrains it to only reference facts present in the input, attach a source link to every claim, and avoid Markdown; a code-level post-processing step also strips anything the model writes after the last event's link, since small local models don't reliably follow "don't add a sign-off." Falls back to a non-LLM template if Ollama is unreachable/fails or when the event list is empty. |
| 4. Preview / Review | `preview.py` (Streamlit app) | Human-in-the-loop UI: generate a draft, edit it freely in a text box, then confirm before sending. No pipeline step past generation runs without an explicit click. |
| 5. Send | `send.py` (`send_newsletter()`) | Sends the (possibly hand-edited) email body over Gmail SMTP. On success, writes the sent events' keys back into `state/sent_log.json` so they won't resurface; on any failure, nothing is marked sent so those events are retried next run. |
| 6. Orchestration | `run.py` (`build_draft()`) | The single place that wires collection + dedup + generation together, so the CLI and `preview.py` share one implementation instead of duplicating the sequence. |

## Setup

### 1. Install dependencies

> **If your project folder lives inside iCloud Drive / Dropbox / OneDrive**
> (anything under `~/Library/Mobile Documents/...` counts), **create the
> virtualenv outside that synced folder**, e.g. in `~/.venvs/`. A venv has
> tens of thousands of small package files; putting it inside a synced
> folder means the sync client can evict them to "cloud-only" at any time,
> and the next `import` has to re-download each file one by one --
> observed firsthand as a multi-minute hang on this exact project when the
> venv was created inside iCloud Drive. The project's own `.py` files are
> few and small enough that this isn't a practical problem for them --
> it's specifically the dependency-heavy venv that needs to live elsewhere.

```bash
python3 -m venv ~/.venvs/newsletter
source ~/.venvs/newsletter/bin/activate
pip install -r requirements.txt
```

(Run `source ~/.venvs/newsletter/bin/activate` again in any new terminal
tab before running anything below.)

### 2. Install Ollama and pull the model

`generate.py` calls a local Ollama model instead of a cloud API -- no API
key needed for this layer.

```bash
brew install ollama       # if not already installed
ollama serve &            # start the local server (leave it running)
ollama pull qwen2.5:7b    # one-time download of the model used by generate.py
```

### 3. Configure `.env`

```bash
cp .env.example .env
```

Then fill in real values for:

- `SENDER_EMAIL` -- the Gmail address the newsletter is sent from.
- `SENDER_APP_PASSWORD` -- **not your normal Gmail password.** This is a
  Google App Password: a 16-character code generated separately for one
  app/device, only available once 2-Step Verification is turned on for
  that Google account. Generate one under the account's Security settings
  (search "App Passwords" in Google Account settings -- roughly
  myaccount.google.com -> Security -> 2-Step Verification -> App
  passwords).
- `RECIPIENT_EMAIL` -- who receives the newsletter.

`OLLAMA_HOST`, `OLLAMA_MODEL`, `VOLTA_EVENTS_URL`, and
`EVENTBRITE_HALIFAX_TECH_URL` are already filled in with working defaults
-- no need to touch those unless you're pointing at a different model or
a remote Ollama instance.

`config.py` validates the required variables above at import time and
raises a clear `RuntimeError` naming whatever's missing, so a
misconfigured `.env` fails immediately instead of causing a confusing
error mid-run.

### 4. Reset dedupe state before demo / before each fresh test run

```bash
echo "[]" > state/sent_log.json
```

Every test run of `send.py` (even with fake data) permanently records
those fake events as "sent." If you don't clear this before the real demo,
a live fetch can come back "10 events found, 0 new" -- not because
anything is broken, but because last night's test data is still sitting
in the dedupe log. Treat this reset as a pre-demo checklist item, same
tier as checking the mic works.

## How to run

### Command line

```bash
python run.py          # preview only -- fetches, generates, prints the draft, sends nothing
python run.py --send   # same preview, then asks "Confirm send? (y/n)" before actually sending
```

Anything other than `y` at the confirmation prompt cancels cleanly --
nothing is sent, nothing errors.

### Web UI

```bash
streamlit run preview.py
```

Three sections on one page:

1. **Generate this week's draft** -- click to fetch + dedupe + generate a new draft.
2. **Review & edit** -- the draft appears in an editable text box; change anything before sending.
3. **Send** -- click "Confirm & Send," then confirm again in the "Are you sure?" prompt to actually send. Editing the text box or any other interaction never re-triggers fetching or generation -- only the "Generate" button does.

## Known limitations

- **Dedup is exact-match only.** It compares event URL (or `title|date`
  when there's no URL) -- there's no semantic matching, so the same event
  listed with slightly different titles across sources would be treated
  as two different events.
- **Eventbrite's page structure hasn't been stability-tested over time.**
  Both sources are scraped via embedded schema.org JSON-LD rather than
  fragile CSS classes, which is a stable *pattern*, but neither source has
  been observed over more than one evening -- a future redesign of either
  site could break extraction without warning.
- **Single audience, no segmentation.** One newsletter body goes to one
  recipient list; there's no support for different content per audience
  segment.
- **Generation degrades to a plain template if Ollama fails.** If
  `ollama serve` isn't running, the model isn't pulled, the request times
  out, or the event list is empty, `generate_newsletter()` returns a
  deterministic, non-LLM bullet-list version instead of raising --
  readable, but without the LLM's phrasing.
- **Local generation is slow and needs prompt reinforcement.** On this
  project's dev machine, one `qwen2.5:7b` generation takes roughly 2-3
  minutes on CPU -- noticeably slower than a cloud API call, and worth
  planning around live during a demo. It's also less reliable than a
  larger hosted model at following negative instructions ("don't sign
  off," "don't use Markdown"); the prompt has been hardened against the
  issues observed so far, and one sign-off case is enforced in code
  rather than left to the model, but a different local model or prompt
  change could surface new instruction-following gaps that need the same
  treatment.

## Possible next steps

- **If Volta can provide access to a member roster,** a "new members" section could be added as a second, independently-sourced input into `generate_newsletter()`.
- **If semantic duplicate detection becomes necessary** (the same event appearing under different titles across sources), that could be layered on top of the current exact-match filter as an optional second pass, rather than replacing it -- keeping the free, deterministic filter as the first line of defense.
- **If a non-Gmail sending volume or deliverability need comes up,** `send.py` could be swapped for a real ESP (SendGrid, Mailchimp, etc.) behind the same `send_newsletter(body, events) -> bool` signature, with no changes required upstream.
- **If more event sources are needed,** `collect.py` is already structured for it -- add a `_fetch_<source>()` function and register it in `fetch_events()`'s loop.
- **If the goal shifts toward less manual review over time,** that's only worth considering after a few weeks of `preview.py` usage data on how often edits are actually made before sending.
- **If local generation proves too slow or unreliable for regular use,** `generate_newsletter()`'s Ollama call could be swapped back for a hosted API behind the same function signature, without changing `run.py` or `preview.py`.
