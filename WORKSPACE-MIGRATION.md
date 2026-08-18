# Handoff: fold this into Farell AI Workspace

This brief is written to be pasted into **Claude Code running on the Mac**, where
the workspace is actually reachable. It was produced from a cloud session that
could see this repository but not `/Users/tanubrataf/Farell AI Workspace`, so
every statement about the workspace below is an **inference from the skill
files**, not something that was read from the workspace itself.

## The one rule that outranks this document

`WS/CLAUDE.md` is the authority. Read it first. Where anything here disagrees
with it, CLAUDE.md wins and this file is wrong. The same goes for `CONTEXT.md`
and `AUTONOMY.md` if they carry structural rules.

Do not move or rename anything before showing the plan and getting a yes.

---

## Scope

Three projects. They are in two different situations.

| Project | Where it is | What it needs |
|---|---|---|
| Buffett stock valuation agent | This repo, branch `claude/buffett-stock-valuation-agent-mm48gt` | Bring into the workspace |
| PRD maker | Already in the workspace | Audit in place against CLAUDE.md |
| Budget planner | Already in the workspace | Audit in place against CLAUDE.md |

Only the first one moves. The other two are already home and just need to be
brought in line with the conventions.

---

## Step 1: read before touching

```
WS=/Users/tanubrataf/Farell\ AI\ Workspace
cat "$WS/CLAUDE.md" "$WS/CONTEXT.md" "$WS/AUTONOMY.md" 2>/dev/null
ls -la "$WS"
```

Then locate the two existing projects. They were not visible from the cloud
session, so their actual paths are unknown. `WS/playbooks/prd.md` exists and may
be the PRD maker, or may be a separate playbook that merely relates to it.

```
find "$WS" -maxdepth 3 -iname "*prd*" -o -maxdepth 3 -iname "*budget*"
```

## Step 2: audit the two that are already there

For each of PRD maker and budget planner, produce a short findings list before
changing anything: what it is, where it sits, which conventions in CLAUDE.md it
already follows, and which it breaks. Then propose the moves and renames as a
plan. Apply only what gets approved.

Things worth checking, assuming the conventions in the next section hold:

- Does it write outputs to a `{domain}/outputs/` folder, or somewhere ad hoc?
- Are output filenames `YYYY-MM-DD-{slug}.{ext}`?
- Does it build paths from `WS`, or does it assume a working directory?
- Are timestamps WIB and labelled as WIB?
- Does it write to `STATE.md` / `CONFIRM.md` where it should, and stay out of
  them where it should not?

If a project already follows CLAUDE.md, say so and change nothing. An audit that
finds nothing is a real result, and churn on a working project is a cost.

## Step 3: bring in the Buffett agent

```
git clone https://github.com/farelladiputra-create/Future.git
cd Future && git checkout claude/buffett-stock-valuation-agent-mm48gt
```

Verify it runs before placing it. This needs no keys and no network:

```
pip install -r requirements.txt
python -m pytest tests/ -q          # expect 150 passed
python -m buffett.run --offline --no-notify --output-dir /tmp/demo
```

**Proposed placement, to confirm against CLAUDE.md.** The workspace already uses
a `{domain}/outputs/` pattern for `dana/` and `job-search/`, so the consistent
shape is:

```
WS/investing/
├── agent/          the Python package, config.toml, tests
└── outputs/        YYYY-MM-DD-buffett.{md,html,json}, latest-buffett.html
```

This is the piece most likely to be wrong, because the workspace pattern was
inferred from output paths in skill files, and none of those skills ships a code
package. If CLAUDE.md says code lives elsewhere, follow that instead: only the
two config values in the next section need to change.

### Wiring it to the workspace

The repo was already adjusted for the conventions, so this is configuration
rather than code:

```toml
# config.toml
[report]
workspace_root = "/Users/tanubrataf/Farell AI Workspace"
output_dir = "investing/outputs"
slug = "buffett"
```

Or leave the file alone and export `FARELL_WS`, which overrides it.

With that set, reports land at absolute paths under the workspace and are named
`YYYY-MM-DD-buffett.md`. `tests/test_workspace.py` covers this.

### Scheduling it locally

The repo ships a GitHub Action at 14:00 UTC Tuesday to Saturday, which is 21:00
WIB. If the agent should instead run on the Mac and write straight into the
workspace, use launchd or cron and **drop the UTC conversion**, since a local
crontab is already in WIB:

```cron
0 21 * * 2-6  cd "$WS/investing/agent" && /usr/bin/python3 -m buffett.run >> "$WS/investing/agent/run.log" 2>&1
```

Tuesday to Saturday, not Monday to Friday: at 21:00 WIB the New York close has
not happened yet that day, so each run reads the previous session. `Monday` would
only re-read the Friday close that Saturday already covered.

Decide whether it runs in CI or on the Mac, not both. Two schedules writing the
same dated files into the same folder will fight.

---

## Conventions, as reconstructed

Every line here came from `build`, `today`, `prep`, and `review-contract` skill
files. Treat it as a starting hypothesis to check against CLAUDE.md.

**Layout**

```
Farell AI Workspace/
├── CLAUDE.md  CONTEXT.md  AUTONOMY.md      instructions and rules
├── STATE.md   CONFIRM.md                   shared state, queue, open items
├── analysis/
├── builds/                                 drop zone
│   └── done/       YYYY-MM-DD-{slug}.{ext}
├── dana/outputs/   prep-YYYY-MM-DD-{slug}.md, contract-review-YYYY-MM-DD-{slug}.md
├── digests/        YYYY-MM-DD.md
├── job-search/outputs/
├── personal/inputs/
├── playbooks/      prd.md, message.md, data-analysis.md
├── samples/        OBSERVED-VOICE.md, OBSERVED-MESSAGING.md
└── templates/
```

**Rules of thumb**

1. Absolute paths built from `WS`. Never assume the working directory.
2. WIB (UTC+7) for every timestamp, labelled as WIB.
3. Dated, slugged filenames: `YYYY-MM-DD-{slug}.{ext}`.
4. Domain folders own their outputs: `{domain}/outputs/`.
5. `STATE.md` and `CONFIRM.md` are shared. One owner per kind of entry, and
   nothing writes a competing version of something another skill owns.
6. Bahasa Indonesia for personal artifacts, natural rather than stiff, finance
   and product terms left in English.
7. No em dashes.
8. Never invent a number. Missing data is labelled missing.

Rules 6 to 8 come from `farell-work-style` and `jarvis-slate-brand` and the
Buffett agent already enforces all three, with tests.

---

## What was already changed here, so Step 3 is short

- `report.workspace_root` and `report.slug` added to config, with `FARELL_WS` as
  an environment override.
- Output paths now resolve absolutely against the workspace root instead of the
  working directory.
- Report filenames carry the slug, so several agents can share one outputs folder.
- `tests/test_workspace.py` covers all of it: seven tests.

What was **not** changed, because it needs the workspace in front of you:

- Where the package finally sits.
- Whether the agent should append to `STATE.md` when it finds an actionable buy,
  and whether `CONFIRM.md` is the right place for a position awaiting a decision.
  Both look plausible from the skill files and neither was built on a guess.
