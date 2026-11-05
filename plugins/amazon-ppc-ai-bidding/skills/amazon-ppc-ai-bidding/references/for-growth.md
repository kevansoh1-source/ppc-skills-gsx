# For Growth: the listing-pass hand-over to the Growth team

Written 2026-10-22 (SGT), from the code as built that day. Time is Singapore time. The design is the addendum
[2026-10-22-for-growth-tab-design.md](../../../../docs/superpowers/specs/2026-10-22-for-growth-tab-design.md) (its
section 2b, the evidence gate, was adopted by Kim on 2026-10-22 at 00:55 SGT) on top of the launch design's section 4,
[2026-10-20-launch-process-ai-growth-design.md](../../../../docs/superpowers/specs/2026-10-20-launch-process-ai-growth-design.md).
The code is `scripts/growth.py` (the rules, the item, the two renderers), `plan.py` (`plan_growth`, `load_listing`),
`human_review.py` (the `growth` kind and its merge), `dashboard.py` (the `growth` command, statuses, the close, the
keys), `dashboard/server.ts` (the status route) and `dashboard/growth-ui.js` (the tab and the card).

**What it is.** When the data says a product's listing copy should change, the weekly run hands the Growth team one
paste-ready block: which searches to weave in, which carried terms to move down or remove, and which searches are an
offer problem (image, price or reviews) rather than a copy problem. It is one `human_review` item per ASIN, `id`
`for-growth`, `kind` `growth`, lane `growth`, owner `Growth`. Growth pastes the block into the listing optimizer and
pushes the copy in Seller Central. Nothing here writes to Amazon or to a listing.

**It is not a Needs-human item.** It is out of the Needs-human queue and out of "N decisions need you", it has no
approval level (nobody signs it), and it skips the market-research gate (its rows are deterministic;
[needs-human.md](needs-human.md), "Kind growth"). On an AI-managed product it supersedes the `listing-conversion-gap`
item, which was built from the same below-market signal.

## The block contract is Growth's

The block's form is defined by Growth's file
[ppc-handover-block.md](../../listing-build/skills/growth-listing-optimizer/references/ppc-handover-block.md) (v4.7,
2026-10-21), read by their `scripts/growth_block.py`. **That file is the contract. The PPC side renders to it and never
redefines it, and this repo never edits it.** In short, so you can check a block by eye (the reference has the exact
rules):
- Header `## For Growth: <ASIN> <product>`, then four `- Key:` lines: `Produced` (SGT), `Pass`, `Stage`, `Command`.
- Tables under `### Swap table`, `### Rotate out (watch list)` and `### Offer problems`, then `### Notes`, with the
  reference's exact column names. A table with no rows is left out. No `|` inside a cell (`growth.py` writes `/`).
  A blank cell means unknown, never 0.
- The command's seeds are the swap table's `in` rows, in the table's order: `/growth-listing-optimizer <ASIN>
  --seed-keywords "a; b; c"`. Removals and move-downs are never seeds. With no `in` row the command is the bare
  `/growth-listing-optimizer <ASIN>`.
- The item carries the block in both of the reference's forms: `growth.block_md` (markdown, what the card shows and
  Copy block copies) and `growth.block` (the JSON twin). `scripts/test_growth.py` renders both and reads them back with
  Growth's own parser, so the two sides cannot drift without a test failing.

**Where the PPC side differs from the reference's wording.** The reference was written on 2026-10-21, before Kim
adopted the evidence gate. Its "every 12 weeks after day 56" is replaced, on the PPC side, by the floor, gate and
ceiling below. And where the reference tags a flag block `second optimization onward`, the PPC side tags a flag raised
before any pass has been resolved `first listing optimization` (the flag brings the first block forward, design
section 3). The block's form is unaffected; Growth's reader takes either tag. The reference is Growth's file to update.

## When a block is raised

Only a product whose file has `growth.enabled: true` raises anything (the default is off,
`config.json` `growth.enabled_default`; section "Commands" below). Everything else in this section is the weekly run
(`plan.py`, step 5 of [weekly-run.md](weekly-run.md)) except `manual`.

**Dates.**
- **Anchor** = the later of the Monday board's launch date (`launch_date` in the product file) and the product's first
  ad click, or the one that is known; a person can set it by hand (`source: hand`, which wins and stays). Sources:
  `monday_launch_date` (also on a tie), `first_ad_click`, `hand`. A first click that falls on the first day of the
  90-day click series is not counted (it lies before the series, so the launch date stands). Kim, 2026-10-21: "as
  long as a product launch date on monday.com has 8 weeks or when the first click is made, then from there the 8 weeks
  is measured."
- **The first pass comes on evidence, not on a date** (Kim, 2026-10-25, [decision 124](../../../../docs/decisions.md);
  `growth.first_pass_mode` `evidence`). The hand-over fires when the AI bidding audit has enough data and confidence to
  name the SKC keywords: see "The first pass on evidence" below. Day 56 (`growth.first_pass_days`) is used only when the
  mode is set back to `date`.
- **First-pass ceiling** = the later of the anchor and the day the switch went on (`growth.enabled_on`, written by
  `growth --enable`) + `growth.pass_ceiling_weeks` (26 weeks), while `growth.first_pass_ceiling` is true. It is a safety
  net so a product never waits forever. Counting from the switch keeps the products enabled long after their launch from
  all firing in the first run.
- **After a resolved pass** the next window is `no_earlier_than` = the last listing change + `growth.pass_floor_weeks`
  (8 weeks) and `by` = the last listing change + `growth.pass_ceiling_weeks` (26 weeks). Before the first pass the
  window is `{no_earlier_than: null, by: <the first-pass ceiling>, on_evidence: true}` (in date mode both dates are the
  first due date). The window is stored in the product file (`growth.next_pass`) so the page and the tab show it without
  a run.
- **Quiet** = `growth.quiet_days` (30) after the last listing change. The last listing change is `growth.last_listing_change`
  (set by the AI's close, below), else the latest resolved pass's `resolved_on`.
- **Worked on the gel pens (B0SAMP0012):** launch 2026-09-25. Switched on 2026-10-25, its first pass comes when two
  proven SKC keywords hold for two runs, and by 2027-04-25 at the latest. If the first pass is on 2026-11-20 and the copy changes
  that week (the close is dated the publish day), flags wait until 2026-12-20, and the next window is no earlier than
  2027-01-15 and no later than 2027-05-21.

**Triggers.** These six and nothing else. The tag is the item's `growth.trigger`.

| Trigger | Fires on | Pass tag |
|---|---|---|
| `first_pass` | an enabled product with no resolved pass, on a run where the data floor holds and `growth.skc_min_proven` (2) proven SKC keywords the copy does not carry have held for `growth.pass_persist_runs` (2) runs (below). In date mode: the first run on or after the first due date | `first listing optimization` |
| `evidence_pass` | after a resolved pass, a run on or after `no_earlier_than`, with the evidence gate open (below) | `second optimization onward` |
| `ceiling_pass` | the first run on or after `by`, when no evidence pass fired in the window: after a resolved pass, or before the first one at the first-pass ceiling | `second optimization onward` (`first listing optimization` before a resolved pass) |
| `rotate_out_flag` | any weekly run, before or after the first pass, when a carried term meets the flag bar and it is outside the quiet window | `first listing optimization` until a pass is resolved, then `second optimization onward` |
| `new_skc` | since 2026-10-29 (Kim, decision 167): a search with its own SKC in the invest log that the live copy does not carry and no earlier block offered. It refreshes an open item (which then offers the search), or opens a new one at most every `growth.new_skc_min_days` (14) after the previous item opened and outside the quiet window. Needs this run's `listing.json` | as above |
| `manual` | `dashboard.py growth --asin <ASIN> --run <run> --emit`, any day (below) | as above |

The pass tag is `first listing optimization` until the product has a resolved pass (a `growth.passes` entry with a
`resolved_on`), then `second optimization onward`. When several triggers hold in one run the order is flag, evidence,
ceiling, first; `new_skc` sits after the flag and before the scheduled triggers, and is the only one besides a flag that refreshes an open item.

**The first pass on evidence** (Kim, 2026-10-25, decision 124). The first block is raised on the first run where
both hold:
- **The data floor** (rule 1): the product's stage is not `launch`, and it has at least
  `growth.first_pass_min_trusted_queries` (5) trusted queries (searches with 10 or more of our clicks in the SQP
  window). Below that, the market index is too thin to judge the copy by.
- **Two proven SKC keywords the copy does not carry, for two runs in a row** (`growth.skc_min_proven`,
  `growth.pass_persist_runs`). A proven SKC keyword is a search the planner rates **Rank / Invest on SQP's own
  same-query index**: 3 or more orders at an index of 1.1 or more, on 150+ searches (the rulebook's evidence ladder,
  `growth.proven()`). Not proven: Prove first rows, the product-market fallback (no SQP row yet), season rank searches,
  business searches, retained log entries and invest-log searches the plan no longer rates. A search the last block
  already offered does not count again.

The counts are `growth.candidates.uncarried_proven` (`{term: runs}`), advanced on every run like the others below. The
block itself is unchanged: its weave-in rows are still every funded search the copy misses, Prove first included.

**The flag bar.** A carried term (the live listing holds all its words) that is not funded and not a head noun, with
`growth.rotate_out_min_clicks` (30) or more of our SQP clicks in 90 days and either 0 purchases or an index under
`growth.rotate_out_index` (0.5), and not kept by the block's own shield (`growth.sqp_shield_purchases` 3 SQP purchases,
or an SQP index of `growth.sqp_shield_index` 0.8 or more; open item 49, closed 2026-10-25: a flag would only ask Growth
to keep what it flagged). Not for a term already flagged on the item that is still open. A flag found inside the
quiet window waits: it is kept in `growth.candidates.flags_waiting` (`{term, seen, until}`) and raised on the first
run on or after `until`, if the term is still at the flag bar on that run's data. The flag bar and the pass bar below
are two different numbers: the flag bar only decides whether an unscheduled item is raised.

**The evidence gate** (second pass onward, between the floor and the ceiling). It is open when, on this run and the
previous one (`growth.pass_persist_runs`, 2):
- at least `growth.skc_min_proven` (2) proven SKC keywords are not carried by the listing (since 2026-10-25; it was
  any 2 funded searches, `pass_min_new_funded`), **or**
- one carried term sits under the pass bar (17+ SQP clicks and an index under 0.8, not shielded), **or**
- the product's stage changed since the last pass (for example `early` to `mature`).

How it counts, because the details decide when a pass fires:
- Counts are kept in the product file's `growth.candidates` (`uncarried_proven`, `uncarried_funded` and `under_bar`,
  each `{term: runs}`; `uncarried_funded` is kept for the record and no longer opens the gate;
  `stage`; `flags_waiting`; `date`). `plan.py` advances them on **every** run, enabled or not, and `dashboard.py publish`
  or `refresh --run` stores them from `<run>/growth.json`. A term absent from a run drops out and restarts at 1. Counts
  also build during the 8-week floor, so a gate open since week 6 fires on the first run at week 8.
- Only funded searches the previous block did not already offer as an `in` row count (a search Growth was handed and
  rejected would otherwise reopen the gate every floor). An under-bar term counts only where a move-down is possible
  (not a term only in the backend) and the previous block did not already offer it as a move down or remove. What
  Growth rejected still rides the ceiling pass.
- A re-run on the date already counted is not a new run. A run with no `listing.json` knows nothing about the copy, so
  every count, the date and `flags_waiting` carry forward unchanged.
- The stage compared is the last pass's recorded `stage`, else the previous item's `growth.stage.name`.

**What holds a window.**
- **An item that is not closed holds the scheduled window.** The first, evidence and ceiling triggers fire only with no
  previous item or a closed one (closed = `resolved` or `dismissed`). Only a rotate-out flag updates an open item. Weekly
  runs never refresh an open block, so "Picked up" always means the block Growth actually read (design section 7).
  `growth --emit` is the by-hand fresh block.
- **A dismissed item holds the schedule for the 8-week floor** (from its `resolved_on`, which a dismissal stamps).
  A dismissal adds no `growth.passes` entry, starts no quiet clock and does not change the pass tag.
- **A dismissed flag stays quiet for the same 8 weeks:** the dismissed item's `growth.flags` terms count as
  already flagged until the hold ends, then may fire again. A new term still fires inside the hold; the item it opens
  carries the dismissed terms in `growth.flags_held` (`[{term, until}]`), so they stay quiet on it too.
- **A flag on an open item** is the one thing that updates it: the new block replaces the old one, the status, who set
  it and the history are kept, `growth.flags` gains the term, and the next publish writes an activity line "rotate-out
  flag on <product>: <term>".
- **Roots and the listing are inputs.** With no `relevance.roots` (or `launch.roots`) in the product file there are no
  rotate-out rows and no flags, because the head-noun exemption cannot be applied (the block's Notes say so). As of
  2026-10-22 only B0SAMP0012 (`["pens"]`) and B0SAMP0013 (`["notebook", "notebooks"]`, added in the shadow run) have
  roots, so add them before enabling any other product (open item 47). With no `listing.json` in the run
  the item is weave-ins only, every `in` row sitting today as `unknown`, with no `out` rows and no flags.

## What is in the block

The same funded-and-carried tests as the planner, in `growth.py`.

- **Funded** = a Rank row with role Invest or Prove first in this run's plan, plus every search in the product's
  `invest_log` (it stays funded until a person steps it down).
- **Carried** = every content word of the search (lowercase, apostrophes dropped, the words `for the a an of and with to in on`
  dropped, a trailing `s` folded) is found in one surface of the listing: title, highlight, bullet 1 to 5, backend, read in
  that order. A backend that could not be read is `null`, never "absent", and the Notes say it.
- **In rows (weave in).** Funded searches the listing does not carry, placed in **sales-potential order** (Kim,
  2026-10-26, decision 138): SQP searches × market CVR × index, the purchases we would expect in the SQP window at a full
  share of the search (rows with no SQP number come last, by volume × index). In that order each row's slot is the first
  of: **backend** for a search carrying the brand word (`yourbrand`); **backend** for a spacing variant of a carried word,
  or a proven low-volume harvest (under `growth.offer_min_volume`, with a purchase); **bullet** for a seasonal search
  (one of `growth.seasonal_words`, like "back to school" or "christmas", that is not part of the product itself: evergreen
  searches take the title and the highlight); **title** for a niche-qualified search of any funded role, up to
  `growth.title_slots` (3) a block; **highlight**, up to `growth.highlight_slots` (2), for a niche-qualified search, a
  search made only of the product's own name words that the copy lacks (Growth's reference puts `pastel gel pens` there)
  or a modifier or secondary occasion ("for women", "with envelopes", "bulk"); else **bullet**. Until 2026-10-26 only an
  Invest search could take the title and rows were ordered by volume × index. No product file has `relevance.qualifiers`
  today, so "niche-qualified" falls back to the planner's head-term check (two words or more, no relevance flag). Slots
  are suggestions: Growth's optimizer has the last word.
- **Out rows (the swap table's `remove` and `move down`).** They start from a carried, non-funded term that is not a head
  noun (`relevance.roots`, `launch.roots`). If it is **irrelevant** (the Negate role, or matched by the product's
  `relevance` lists) it is **removed from every surface**, backend included, whatever SQP says. If it is **below market**
  and not shielded it is **moved down** one level (title or highlight to a bullet, a bullet to the backend; a term
  already in the backend has nowhere lower and shows on the watch list only).
- **The pass bar.** Below market = SQP basis, not thin, `growth.judge_clicks` (17) or more of our SQP clicks, index under
  `growth.below_market_index` (0.8). A search-term (ad report) basis is never a move-down, because the shield cannot be
  applied. Shield = `growth.sqp_shield_purchases` (3) or more SQP purchases, or an SQP index of
  `growth.sqp_shield_index` (0.8) or more. **There is no confidence term on this bar:** the Trim lane holds no cut back
  (rulebook 7.3), so a move-down is not held back either. The "about N% sure" text in the row's Why is information only.
- **Never Out:** a funded search (an invested search leaves through the stop-loss review, not through the copy) and a
  head noun. Irrelevant removals are not SQP-shielded.
- **Rotate out (watch list).** Every carried, non-funded, non-head-noun term at the pass bar or the flag bar, whether or
  not the swap table acts on it, with the bar in words (which condition a term missed, the shield that applied, and
  whether the planner's flag bar is met too).
- **Offer problems.** Relevant searches with `growth.offer_min_volume` (150) or more searches a month that convert
  below market on the same bar. Labelled image, price or reviews work, not copy, with the planner's bid action (Hold or
  Trim and any bid change this run). A price idea is a separate `price` item that Kim approves.
- **The Stage line** comes from `summary.stage`: the stage name, the SQP window (`SQP 90 days to <date>`), the longest
  observed-day count and the number of queries with `thresholds.trusted_min_clicks` (10) or more of our clicks. The stage
  decides depth, in Growth's rules (an early-stage edit stays in bullets and backend): the engine reports the stage and
  does not pre-filter.
- **A launch-stage product** exits the planner before the For Growth step ("<ASIN> is in the launch stage ..."), so a
  weekly run writes no `growth.json` for it. Until launch mode is built, its block comes only from `growth --emit`
  (design section 3): the stage line says `launch (no SQP yet: DataDive weave-ins only)` and the weave-ins are the
  product's `launch` list median set, DataDive basis, no index. `--emit` reads `<run>/plan.json`, which the launch-stage
  exit does not write, so for this case make a minimal one by hand (`summary[0].asin` and `summary[0].stage.stage:
  "launch"`), and add `listing.json` to the run.

## The item

Item level (the `needs-human.md` contract): `id` `for-growth`, `kind` `growth`, `title` "For Growth: <pass> for
<product>", `reason`, `action`, `source`, `window` ("SQP 90 days to <date>; ads 90 days"), `evidence` (query rows, one per
swap side and offer problem), `owner` `Growth`, `status`, `status_by` and `status_at` (who set it and when, from the
dashboard click), `priority`, `first_seen`, `last_seen`, `ai_review.phase` `human_ready`, `workflow.lane` `growth`
(`workflow.proof` once closed), `history`, and `resolved_on` and `resolution` once closed. No `approval_required`.

The `growth` block:

| Field | Holds |
|---|---|
| `asin`, `product` | the product |
| `produced` | when the block was made, `YYYY-MM-DD HH:MM SGT` (the run's date and the clock's time; `--emit` stamps the real emit time) |
| `pass` | `first listing optimization` or `second optimization onward` |
| `trigger`, `trigger_reason` | one of the five triggers, and its reason in words |
| `opened_on` | the day this pass opened. The item id is the same every pass, so the dashboard counts Growth's clicks only from this day and an earlier pass's clicks never show on a new one |
| `stage` | `{name, window, observed_days_max, trusted_queries}`; `trusted_min_clicks` is the click floor behind the last count |
| `window` | `{sqp_data_through, days}` |
| `anchor` | `{date, source}` |
| `due` | the date this pass became due: the `by` date for `ceiling_pass`, else the run's date (in date mode, the first due date for `first_pass`) |
| `next_pass` | `{no_earlier_than, by}`, the window the item was raised in (before a resolved pass in evidence mode, `{no_earlier_than: null, by, on_evidence: true}`) |
| `candidates` | the gate's bookkeeping (above) |
| `listing_snapshot` | the `listing.json` the block was built on, or `null` when the run read no listing; the close compares a later listing with it |
| `swaps`, `weave_in`, `rotate_out`, `offer`, `command`, `note` | the rows the block is rendered from (`swaps` is `{slot, out, in}` pairs) |
| `flags` | the rotate-out flags raised on this item, `{term, slot_now, our_clicks, our_purchases, index, date}` |
| `flags_held` | only while a dismissal holds terms quiet: `[{term, until}]`, the dismissed flags not to raise again before `until` ("What holds a window") |
| `block_md`, `block` | the block in Growth's two forms |

**`<run>/growth.json`** is written on every run, with or without an item. It always holds `asin`, `item` (the item made
this run, else `null`), `trigger`, `trigger_reason`, `anchor`, `next_pass` and `candidates`. **It holds a block (the
reference's JSON keys at top level: `product`, `produced`, `pass`, `stage`, `command`, `swaps`, `rotate_out`,
`offer_problems`, `notes`) only when `item` is not null.** Growth's reader accepts a file with no item silently and
shows an empty table (checked 2026-10-22: `growth_block.py --template` prints an empty table and assumes the first
pass), so look at `item` before reading it as a block. `dashboard.py publish` and `refresh --run` store the run's
candidates, and the anchor when the product file has none, from this file.

## Lifecycle and the two buttons

`open` (made by the run) then `in_progress` (**Picked up**: "I am on it") then `copy_pushed` (**Copy pushed**: "the new
copy is submitted in Seller Central") then `resolved` by the AI, or `dismissed` by a person. `copy_pushed` is valid on a
growth item only. Skipping straight to Copy pushed is fine.

- **The clicks** are `POST /api/items/<ASIN>/for-growth/status` on the dashboard, signed with a Growth key or a
  personal token ([dashboard.md](dashboard.md), "For Growth"; [docs/growth-dashboard-login.md](../../../../docs/growth-dashboard-login.md)).
  The server record is authoritative and append-only. `dashboard.py reviews --asin <ASIN> --save <run>/reviews.json`
  also saves them as `<run>/item_statuses.json`, and `dashboard.py publish` (and `growth --emit`) moves them onto the
  item in the product file: forward only, never onto a closed item, and only entries made on or after `growth.opened_on`
  (SGT date). A weekly publish never redraws a picked-up card as open. `refresh` does not move statuses.
- **The AI's close.** At the next publish, an item that is `in_progress` or `copy_pushed` is `resolved` when the run's
  `listing.json` differs from the item's `growth.listing_snapshot` in the title, the highlight or a bullet (spacing
  ignored; a surface one of the two reads lacks is not compared). The close writes `workflow.proof` ("listing changed
  <date>: <surfaces>"), a history line and an activity line, and in the product file: `growth.last_listing_change` (the
  publish date, which starts the quiet clock), a `growth.passes` entry `{pass, produced, resolved_on, stage}` (a flag item
  closed this way counts as a resolved pass), the next window in `growth.next_pass`, and `growth.candidates` cleared (the
  gate starts again on the new copy). **An `open` item never closes on a diff**, because nobody said they were on it.
  This is the only proof the change landed.
- **The close comes before the merge.** A publish applies Growth's clicks and the close to the stored item first. When
  the close fires in that publish, the run's own growth item (planned before the change, on the old copy) is not merged;
  a flag on the new copy waits for a run after the quiet window.
- **Which publish.** Any `dashboard.py publish` does this work: a shadow product's proposed publish (weekly-run.md step
  11) or, since autonomous runs (decision 98, 2026-10-22), the one applied publish of a product whose Auto lane is on
  (step 14.5). The run's autonomous apply covers its change rows only: the For Growth item is never applied, never a
  "For human" line in the run's Slack message, and nothing here writes to Amazon.
- **Stale** (a count on the tab, nothing more): open `growth.stale_days` (45) days with no pickup, or picked up or
  pushed 45 days with no listing change.
- **A person can dismiss** an item that should not be done: `python scripts/dashboard.py review --asin <ASIN> --id
  for-growth --status dismissed --note "<why>"` (preview with `--dry-run`). `review` refuses `resolved` and
  `waiting_approval` on it: only the AI's close resolves a pass, and nobody approves Growth's work.

## Commands (skill folder)

| Command | What it does |
|---|---|
| `python scripts/dashboard.py growth --asin <ASIN> --anchor [--clicks-daily <run>/clicks_daily.json] [--dry-run]` | Computes `growth.anchor` and `growth.next_pass` and writes them to the product file; prints both and the first due date. `--date YYYY-MM-DD --source hand` sets the anchor by hand. A hand-set anchor stays until another `--date`. Stops with nothing written when there is neither a `launch_date` nor a first click |
| `python scripts/dashboard.py growth --asin <ASIN> --enable [--by "Name"] [--date YYYY-MM-DD]` (or `--disable`) | Turns the product's listing passes on or off (`growth.enabled`), with an activity line. Enabling also stores the switch date as `growth.enabled_on` (today in SGT, or `--date`), which the first-pass ceiling counts from. Disabling dismisses an open For Growth item (no run would refresh or close it). Kim or Lee. Since 2026-10-29 (decision 166) every AI product is on, and a publish switches on any AI product left off unless a person disabled it (`growth.disabled_on`) |
| `python scripts/dashboard.py growth --asin <ASIN> --run <run> --emit [--by "Name"] [--dry-run]` | A fresh block by hand (trigger `manual`) from the run's `plan.json` and `listing.json`, any day, stamped with the emit time. Applies saved clicks and the close first, merges into the product file (an open item keeps its status; a closed one starts a new pass) and rewrites `<run>/growth.json`. Never publishes; run `refresh` or `publish` to show it. When the stored block is not older, it says it kept the stored one |
| `python scripts/dashboard.py secrets --personal "<Name>" --role growth` | Makes a Growth key; see [docs/growth-dashboard-login.md](../../../../docs/growth-dashboard-login.md) |

These change the product file only. Commit and push it afterwards ([weekly-run.md](weekly-run.md), step 14.8). The run's
two inputs, `listing.json` and `clicks_daily.json`, are in [data-pull.md](data-pull.md), "The listing and the daily
clicks (For Growth)".

## Config

**Since 2026-10-29 (decision 167):** `quiet_days` 30 -> 14; `new_skc_min_days` 14 (null turns the new_skc trigger off).
`config.json` `growth` (2026-10-22; changed 2026-10-25, decision 124): `enabled_default` false, `first_pass_mode`
`evidence`, `skc_min_proven` 2, `first_pass_min_trusted_queries` 5, `first_pass_ceiling` true, `first_pass_days` 56
(date mode only), `pass_floor_weeks` 8, `pass_ceiling_weeks` 26, `pass_persist_runs` 2, `quiet_days` 30, `rotate_out_min_clicks` 30,
`rotate_out_index` 0.5, `judge_clicks` 17, `below_market_index` 0.8, `sqp_shield_purchases` 3, `sqp_shield_index` 0.8,
`offer_min_volume` 150, `title_slots` 3, `highlight_slots` 2, `offer_max_rows` 12, `seasonal_words` (2026-10-26, decision 138), `stale_days` 45. Changing one is Kim's call (AGENTS.md, approval levels), and
`dashboard/growth-ui.js` keeps its own copy of `stale_days` (a test checks they match).

Per product, in `data/asins/<ASIN>.json`: `growth: {enabled, enabled_on, anchor: {date, source}, next_pass: {no_earlier_than, by, on_evidence},
last_listing_change, candidates, passes: [{pass, produced, resolved_on, stage}]}`. The dashboard card carries
`card.growth = {enabled, anchor, next_pass}`, so the tab and the product page show the dates before any item exists.

## Telling Growth (#3-marketing-traffic and Monday)

Since 2026-10-25 (Kim, decision 124) the run tells Growth itself; PPC's hand step at day 29-37 (filter the search
terms, set Monday board 2 to "Optimise Listing", post "Ready for First Listing Optimization") stops on enabled AI
products. When a run raises a block (any trigger), `scripts/notify.py` prints a second message, `growth`, next to the
run's standup message:
- **Slack:** post `growth.text` in #3-marketing-traffic (`config.json` `notify.growth_channel_id`, C0EXAMPLE02). It names
  the product, the pass, why it fired, the seed keywords and the For Growth card's link.
- **Monday** (Kim, 2026-10-25): on board 2, "2 - Amazon US PPC Launch | Listings Maintenance" (9000000011,
  `notify.growth_monday_board`), find the product's item by its ASIN (column `text3`, contains). **First** set its Status to "Optimise Listing"
  (`notify.growth_monday_status`), **then** move it into the group "[GROWTH TEAM] - For Listing Optimisation"
  (`new_group3973`, `notify.growth_monday_group`; GraphQL `move_item_to_group`). The order matters: a board automation
  moves any item whose Status changes to "Optimise Listing" into "First Listing Optimization (after 1 month)", so a move
  made before the status change is undone (found 2026-10-25). Creating an item with the status already set does not trip it. **No item on board 2** (on 2026-10-25, 29 of the 32 enabled
  products sat on the Focus board 90000000009 or the old board 1 9000000012): with `growth_monday_if_missing` `create`,
  create one in that group, named `growth.monday.item_name` ("<product> (<ASIN>)"), with the ASIN in `text3` and that
  status; leave the Focus or board 1 item where it is. Read the item back after the write. If the group or the status
  label is not there, say so in
  the run log and leave the board as it is.

Both are part of an autonomous run's own steps (AGENTS.md rule 1); a run that raises no block posts nothing here.

## For the Growth bundle (`/listing-build`)

What the PPC side expects of Growth's bundle on an **AI-managed** ASIN (`registry.bid_owner` AI); other ASINs are
unchanged:
- Step 6 of `/listing-build` reads the For Growth card (the block) instead of running `amazon-skc-qualifier`'s
  bucketing, and runs the placement check (which funded searches the copy carries).
- The SKC Optimization Sheet and the Notion SKC Keyword Log stop for those ASINs.
- The card's Out terms (the `remove` and `move down` rows of the swap table) are passed to the optimizer so it drops them
  out loud in its reconciliation table. The watch list rides in the same block and gets a verdict per row too, because
  the block reader requires one for every row (with its number); a watched term may well be kept.

This is the PPC side's statement of the contract, not an edit. **The bundle's own files (`SKILL.md`, the sub-skills'
`INSTRUCTIONS.md`, the agents) are Growth's to change,** and this skill's docs never edit them.

## Going live

The tab, the status route and the Growth keys are built and tested but not live. Putting them live, and enabling the
first products, are Kim's decisions: the steps are in [dashboard.md](dashboard.md), "For Growth", "Going live". On
2026-10-25 Kim chose to enable every mature AI product at once, on the evidence rule (decision 124).
