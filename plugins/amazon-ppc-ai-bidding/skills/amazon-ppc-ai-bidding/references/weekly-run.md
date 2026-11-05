# Weekly run (per AI-managed product)

Target: one session per product per week, same weekday.

Updated 2026-10-24 for execution during the audit on any day and read-back of every row, and on 2026-10-22 for **autonomous runs**
(Kim, decision 98): the run applies its own Auto rows on Amazon (MarketplaceAdPros) and in Scale Insights (the signed-in
browser), publishes the result to the dashboard as applied, and parks only the real human decisions "For human", with one
Slack message per run. Who has to say yes to each change is in [rulebook.md](rulebook.md) section 7. The design is
`docs/superpowers/specs/2026-10-22-autonomous-runs-design.md` (it superseded the 2026-10-19 auto-apply design's human list
and its shadow gate).

## What a run does (since 2026-10-22)

Anyone (Kim, a teammate, Claude Code or Codex) runs it for one product. The agent, with no per-run approval:

1. **Settles the last run** (step 2): the Day-1 check of the previous apply (`autonomy.py day1`: spend over 1.5x the
   weekday average opens a "Day-1 spend" alert for the book owner; Auto stays on, decision 163), then any rows the team approved
   on the dashboard since (`approvals`, `approved/`).
2. **Plans** (steps 3 to 9): pulls the data, finishes its own research (decision 97) and plans.
3. **Applies the Auto rows itself, during the audit** (step 12): `payloads/auto/` through MarketplaceAdPros, and the folder's
   `scale_insights_steps.json` through the signed-in browser ([scale-insights-playbook.md](scale-insights-playbook.md)). It
   reads back every row ("Read back every row"; a mismatch stops the folder and opens an alert, decision 163) and records what went out
   (`dashboard.py applied --folder auto`, then `log_invest.py`).
4. **Publishes the run as applied** to ppc.example.com (step 14.5): what changed, one line of reason each. No proposed
   step, no preview to approve, no research notes.
5. **Parks only the human list "For human"** (rulebook 7.2): the run's Bids item carries only those rows, and the one Slack
   message in #3d-ppc-standup (`notify.py`, step 14.6) recaps what the run did and tags who decides each parked item.
   Rows parked for a person are not applied.
6. **Logs and commits** (step 14.8): the run log, the product file.

A Scale Insights step the browser can't do (signed out, a page that won't load) is not applied: record only the rows that
went out (`applied --rows`), and add the step to the run's "For human" items for the book owner.

Run every command from the skill folder (`.claude/skills/amazon-ppc-ai-bidding`), one product at a time. These names
are used below:
- `<run>`: this week's run folder, `runs/<ASIN>-<YYYY-MM-DD>/` at the repo root (not in git). It is a new folder every
  week.
- `<prev>`: last week's run folder.
- `<day>`: today's date in Singapore, `YYYY-MM-DD`. Pass it as `--date` or `--today` everywhere: `log_invest.py` and
  `publish` otherwise use the machine's date.

## Auto on, and the kill switch

Every change in a plan gets a lane: **Auto**, **For human** (the dashboard's "Needs human") or **Monitor** (rulebook
section 7). What the lanes do depends on the product's `auto.enabled` setting.

| Mode | When | What happens |
|---|---|---|
| **Enabled** (the default since 2026-10-22) | `config.json` `auto.enabled` is `true` (Kim: "turn it on for all AI products", decision 98), and the product file doesn't say `false` | `payloads/auto/` holds the Auto-lane rows, and the run applies them itself (step 12). `payloads/review/` holds only the rows parked for a person. Monitor rows are held back |
| **Shadow** (the kill switch) | `"auto": {"enabled": false}` in the product file `data/asins/<ASIN>.json`, or in `config.json` for every product | Nothing applies on its own: the run plans and proposes only. `payloads/auto/` is empty, `payloads/review/` holds every row that is not held, and the Bids card lists every row for the team to agree or refuse |

- **Since 2026-10-29 (decision 163) no guard switches a product's Auto off by itself.** A read-back mismatch or a Day-1
  spend trip opens an alert ("Read-back" or "Day-1 spend", an open "decision" item for the book owner) and Auto stays on;
  `autonomy.py switch-off` still switches a product off by hand, and config.json `guards.<day1|readback>_switch_off` true
  restores the automatic switch-off. **Turning a switched-off product back on is Kim's call** (rulebook 7.12): remove the
  product file's `"enabled": false`.
- **An onboarding product and a seasonal phase switch are judged like any other since 2026-10-22.** A product with no
  inventory cover file stops at the plan step with what to pull again (decision 168). SQP of any age is planned on
  (decision 172). Stock cover of 14 days or less does not hold rows (Kim, 2026-10-24); the run retains one
  "reorder stock" item for the book owner (`summary.stock_reorder`, step 14.6). `plan.json` → `summary[0]` says which case
  this is: `shadow`, `lanes` (counts), `apply_after`, `stale_reason`, `stock_reorder`, `onboarding_reason`,
  `planned_invest_month` against the $2,000 `invest_guide_month` (`above_invest_guide`), the Auto promotions past the
  product's band (`over_invest_band`, against `invest_band_month`) or past the $60 loss line for one search
  (`over_loss_line`, `loss_line_month`), `program` (the program total) and `repromote_cooloff`. The guide, the bands and
  the program total are information only, never a gate (rulebook 7.5, 7.7, decisions 99 and 100).

## When you may write: during the audit

Kim, 2026-10-24 (decision 114): **apply eligible, authorized changes whenever the operational audit executes,
including weekends and verified scheduled OFF hours. There is no US-weekday restriction or Monday wait.**
An audit or re-audit of an AI-owned product with Auto on is this run and applies its eligible Auto rows (decision 116,
2026-10-24); only the readiness audit of a product not yet AI-owned, an Auto-off product, and a preview, test or shadow
run a person explicitly asks for remain read-only. A failed preflight (git pull, dashboard, connector) stops the writes
and is reported as a blocked autonomous run, never as a read-only re-audit. Preserve shared-campaign exclusions,
human decisions, fresh-state checks, per-week limits, replacement-serving gates and readback controls.

**Report completion within the approved scope (Kim, 2026-10-24).** Shared campaigns already excluded by the
product's approved `ownership_scope`, and all their descendants, are intentionally untouched. Keep them in
scope evidence, but do not count them as remaining actions, Held or For human items, or use them to label the
audit/onboarding incomplete. Check generated recap counts against that boundary before publication; an excluded
candidate is not an execution blocker. Report applied exclusive changes and any genuine exclusive follow-ups
separately, for example: "Exclusive bid changes applied; four new exclusive groups await SI import and protection
verification. Shared campaigns excluded as instructed." Do not suppress unknown ownership or an unapproved
scope, or clear SI protection, actual-serving, readback or due Day-1 checks without evidence.

`summary.apply_after` now records the plan's current marketplace date for compatibility. Older Monday dates
were generated by the retired rule; neither they nor a missing legacy date prevent execution. `approvals`
and `applied --dry-run` retain their non-calendar guards and run immediately before the actual write.

**Dayparting bid consistency:** read the effective exact-ID SI rule (direct rule takes precedence), its
current hourly modifier and Amazon's current bid. Distinguish the desired unmodified base bid, the live
Amazon bid and the SI stored base. Never infer an active modifier from Saturday/Sunday alone, never blindly
divide or multiply all bids by0.85, and never disable or alter shared rules to make a write easier. Write the
intended bid through MAP, independently read it back, then reconcile SI's synchronized base and the next
modifier transition. If evidence shows normalization, correct only the affected exclusive target using the
verified relationship and read it back. Record the desired base and actual live values separately. An actual
mismatch stops the affected work under the existing readback guard; calendar time does not.

**The planner does the base-bid part itself (decision 150, `scripts/daypart_base.py`).** Scale Insights runs a
modifier by lowering Amazon's own bid, and leaves it there through the OFF hours until the next ON hour sets it again
(rule 203's weekend cut, −20% since 2026-10-31 and −40% from Oct 26 to Oct 31, stays in the live bids until Mon 06:00 PT,
21:00 SGT). `plan.py` compares the live keywords
with their Scale Insights stored bids. When at least half read the stored bid times one common factor, it reads every
live keyword, target and SB keyword bid back to its base before pricing: the stored bid when it matches, else
live ÷ factor; a live bid equal to its stored bid stays as it is, because it was written under the modifier and Scale Insights hasn't put the modifier back on it yet. `inventory.daypart` in the summary records the status (`none`, `modifier`, `mixed`, `too_few`), the
factor and how many bids were rebased; quote it in the run log. On `mixed`, the live bids are used as read: check the
rule and its hour before applying any raise. A bid written under the modifier becomes Scale Insights' stored base within about 2 hours (Oct 25;
Oct 26: 240 of 241), and Amazon shows it times the modifier once Scale Insights applies the modifier to it again, until the next ON hour: read it back right after the write, and compare a later
read against the base, not the live bid.

**The skill keeps writes clear of the switches itself (decision 151, `scripts/write_window.py`).** At each ON switch
of rule 203 (weekdays 21:00 SGT, weekends 20:00 SGT while the US is on daylight time; an hour later from Nov 1 to
March) Scale Insights sets every bid from its saved copy, and the saved copy takes a written bid only about 2 hours
after the write. So a bid written in the 2 hours before an ON switch is put back to the old bid. Nobody needs to watch
the clock: the apply step runs `write_window.py check` first (step 12.1), and a write that lands close to a switch gets
a dated re-check (step 12.5). The schedule is `config.json` `write_window`: keep it equal to rule 203.
**Apply as soon as the run finishes, at any hour and any day** (Kim, 2026-10-31, decision 174). The only exception is the
switch hold: no writes in the 2 hours before a Scale Insights rule 203 ON switch, and none in the hour after it.
`scripts/write_window.py check` enforces this. On hold, wait until its `safe_from` time, or park the folder, then apply.
Never wait for 10:00 SGT, office hours or a "safe window" of your own.

**A bid that moved by the modifier at a switch is expected, never a mismatch or a stop (Kim, 2026-10-26, decision
152).** Example: a weekend live bid of $1.28 that reads $1.60 after Monday 21:00 SGT is Scale Insights taking the −20%
off its $1.60 base ($1.60 × 0.8 = $1.28; rule 203's weekend since Kim changed it on 2026-10-31, decision 174; until then
it was −40%, $1.60 × 0.6 = $0.96), and the reverse happens at the weekend switch. A Codex run on Oct 26 stopped on
22 such Sponsored Brands rows and asked Kim; that was the misreading this paragraph exists to prevent. The code
classifies it, so nobody has to work it out by eye. **The factor is read from the bids, never assumed** (Kim,
2026-10-26: the weekend cut may become −20% or −25%): the planner's `detect` and `daypart_base.common_factor` take the
one ratio most moved bids share (0.8 today, 0.6 before 2026-10-31, 0.75 for a −25% weekend), so a bid is always priced from its full base and
the cut is never taken twice. `config.json` `write_window.modifier` is only a starting point; when the bids show another
factor, the plan summary's `inventory.daypart.config_differs` says so: tell Kim, so the config can catch up. A move
from one modifier to another is a switch too, in either direction (Kim: "0.75 moving to 0.6 ... can also be 0.6 moving
to 0.75"): under a modifier the plan's `current` is the base, so a live bid at base × the plan's own factor has not moved
(`dashboard.plan_factor`), and one at base × any other modifier is a dayparting switch.
- `write_window.py check` also holds for the hour after an ON switch (`settle_minutes`, 60): Scale Insights takes a while
  to re-send every bid, SP first and SB later, so a live read in that hour can catch bids on both sides of the switch. Run
  `check` before the live read (step 3) as well as before the apply.
- `write_window.py prewrite` (step 12.2) compares each payload row's plan `current` with a fresh live read. `apply`: go
  on. `replan`: only dayparting moved bids; plan again from a fresh read once `check` says ok (in a new run folder if
  anything of this one went out; rows already written read live as written and are not sent again). Don't ask a person
  and don't call it drift. `stop`: something else changed a bid; say so before applying (AGENTS.md rule 1).
- The read-back (`autonomy.py readback`, `lanes.readback_mismatches(..., modifiers)`) counts a live bid at the written
  bid × the modifier as written (the configured one, or the one most lower-reading rows share): that is Scale Insights
  applying the weekend modifier to the bid we wrote.
- `dashboard.py approvals` skips such a row with the reason "dayparting switch since the plan ... plan again from a fresh
  read", not "changed since the plan".

The former October17 six-bid normalization incident remains historical evidence for these consistency checks,
not a reason to defer all audits. A schedule-controlled pause does not justify unpausing ads, treating OFF
hours as zero demand, cutting replacement routes without delivery, or resetting experiment clocks.

## Which payload folders may be applied

`<run>/payloads/` holds these. MAP is the only write path: never use Scale Insights change sets on an AI-owned product
(`docs/llm-handbook.md`).

| Folder or file | What it holds | May be applied | Check before | Record after |
|---|---|---|---|---|
| `auto/` | The Auto-lane rows (empty in shadow), and `scale_insights_steps.json`, the checklist of its Scale Insights rows for the browser step | Only when the product is enabled, after the current execution checks pass. No approval is needed: the run applies it itself (autonomous runs, 2026-10-22). `applied --folder auto` refuses a product whose Auto is off | `applied --folder auto --dry-run` | `applied --folder auto` |
| `review/` | The rows a person decides (in shadow: every row that is not held) | Only on Kim's explicit whole-run yes on the preview, and only while nobody has decided a row of the run's Bids item on the dashboard. After current execution checks pass | `applied --folder review --dry-run` | `applied --folder review` |
| `approved/` | The rows the team approved on the dashboard, written by `approvals` | Right after `approvals` wrote it, after current execution checks pass | `applied --folder approved --dry-run` | `applied --folder approved` |
| `held/` | What the planner holds back (Monitor), and rows a person's earlier decision or a rank experiment holds | **Never** | | |
| `rows.json`, `payloads/approved_decisions.json`, `payloads/applied_rows.json` | Records: which row is behind each payload row, who approved it, and what went out | **Never.** They are not payloads | | |
| `payload_archive/` | Earlier plans' files, moved aside when a run is planned again | **Never** | | |

- **`payload_manifest.json` is an inventory, not an approval.**
  - It lists the files of `auto/` and `review/` under `files` (path under `payloads/`, folder, rows, SHA-256, and the
    folder's `approval_required`) and the `held/` files apart under `held_files`.
  - Apply only files the current manifest lists under `files`, and only by the rule of their folder in the table. Since
    2026-10-22 `approval_required` is `{auto: false, review: true, held: null}`, and each file carries its folder's flag:
    `auto/` needs no approval, `review/` needs a person's yes, `held/` is never applied. The Scale Insights checklist's
    entry says `apply_via` "Scale Insights web app".
  - `approved/` is built later, so it is not in the manifest. Its `rows.json` and the `approvals` output name its rows.
  - Check a file's hash with `python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`.
  - Never glob every JSON file in a folder. Never apply anything in `payload_archive/`.
- **Visibility and rank-experiment proposals are not payloads.** They need their own execution preparation
  ([visibility.md](visibility.md)); the planner refuses to write them as payloads.

## Rules for every step

1. **Nothing in these commands writes to Amazon.** The MAP applies are separate steps: the agent's own for `auto/` (and
   its Scale Insights checklist in the browser) since 2026-10-22, with no per-run approval; a person's yes first for
   `review/` and `approved/`.
2. **Never apply `held/`, a `rows.json`, `payloads/approved_decisions.json` or `payloads/applied_rows.json`.** They are
   records, not payloads.
3. **`approvals` runs after current execution checks pass, just before the MAP apply.**
   - Weekends and legacy apply_after dates do not cause a refusal; retain all non-calendar checks.
   - Its `--dry-run`, and its decisions-only mode (a closed item, which sends nothing), still run.
   - Run `approvals`, the check (rule 4) and the MAP apply back to back. A decision made between `approvals` and the apply
     would otherwise go out.
4. **Check before every apply, `approved/` included.** Before applying a folder, run its check:
   `python scripts/dashboard.py applied --asin <ASIN> --run <R> --folder auto|review|approved --dry-run`
   - If it refuses, don't apply that folder, and tell the team which rows it names.
   - Run all non-calendar preflight checks immediately before execution.
   - For `listing_size_verified_pause` rows, follow [live-size-pauses.md](live-size-pauses.md): re-read the actual
     listing and retain fresh raw evidence. The check revalidates identity, age and the planned evidence before
     executing these confirmed wrong-size positive-keyword pauses. Unknown/conflicting sizes stay held.
   - It refuses a creation another folder already made. For `approved/`, run `approvals` again with
     `--discard-unapplied`, then check again.
   - It refuses a folder that already went out, whole or in part (any of its rows recorded): "this folder partly went
     out on <date>; don't apply it again — re-plan in a new run folder or settle with approvals". A folder is applied
     once.
   - For `review/` it also refuses while the run is being decided row by row, or when a row of `review/` was declined
     after the plan.
5. **Record only after the apply went through.** `applied` can't tell whether a folder went out: it records whatever the
   folder's `rows.json` names, locks each recorded row and starts its clocks.
   - So run it for real only after the MAP apply went through and every row was read back, straight away, before
     anything else runs.
   - Never run it for a folder that was not applied. To see what it says, use `--dry-run`.
   - Until it runs, `approvals` refuses to touch that run's `approved/`.
   - If a folder went out but `applied` refuses (a decision landed after the check), record it with `--record-anyway`:
     what went out must be recorded. Report the rows the refusal named. They went out against a decision.
   - **If only part of a folder went out** (the apply stopped on a read-back mismatch), record exactly the rows that went
     out with `--rows` ("Read back every row", step 4). The rest stays unrecorded.
6. **Discarding.** `approvals --discard-unapplied` is only for an `approved/` that did NOT go out. **Never discard a folder
   that partly went out: record what went out with `--rows` first.** Discarding then hands out only the rows not recorded,
   and a creation that was recorded never comes back, nor any part of a Sponsored Brands video build whose campaign went
   out (its other keywords are added by hand: "Read back every row", step 4).
7. **`review/` or `approved/`, never both.** For one run, use the whole-run route (`review/`) or the row-by-row route
   (`approved/`).
   - Once anyone has decided a row of the run's item, `review/` is refused.
   - Once `review/` went out, `approvals` refuses the run ("applied whole").
8. **A run folder is planned until something goes out of it.** Once anything of it went out, or `approvals` handed rows
   out, plan in a new run folder. Planning the same folder again before that is fine: the planner moves the earlier
   plan's payloads to `payload_archive/`.
9. **Approvals need `seen`.** An approval counts only when the dashboard sent what the person saw (`seen`: the current
   bid, the new bid and the capped bid on the row, and the budgets, top-of-search boosts and modelled monthly spend it
   shows). Every one must still match the plan: money to the cent, a boost to the whole percent. The Bids card sends it
   ([dashboard.md](dashboard.md)). Until the card and the server's `/api/reviews` routes are deployed (step 0), every approval
   is skipped and only declines lock.
10. **Push the product file whenever `approvals` or `applied` wrote `decisions`, or `autonomy.py` wrote it.** That is
    REQUIRED, not "when asked": the locks (decline, approve and create) and a guard's kill switch live only in
    `data/asins/<ASIN>.json`, and `reviews.json` carries declines only. A teammate's next plan without them can re-propose a
    creation, cut a raise a person approved, or apply on a product whose Auto a guard switched off. Their output says so:
    `locks_written`, `locks_released` or `locks_pruned` above 0, `switched_off` or `entry_added`. Commit and push straight
    away (step 14.8); an autonomous run needs no OK for it (decision 98), a shadow run asks the person. Don't end the run
    without it.

## Steps

0. **The dashboard server must run the `/api/reviews` routes** (`POST /api/reviews/<ASIN>/<itemId>` and `GET
   /api/reviews/<ASIN>`, deployed with Kim's OK: [dashboard.md](dashboard.md)) before this runbook is used.
   - Without them `reviews --save`, the `review/` check and `approvals` fail with "HTTP 404: Not found". The only way
     through is then an unchecked apply with `--record-anyway`.
   - Don't use this runbook until the routes are live.

1. **Registry, claim, pull.**
   - The product is AI-owned and nobody else is working on it: check `python scripts/dashboard.py team`, then claim it:
     `python scripts/dashboard.py claim --asin <ASIN> --what "Weekly run" --until <date>`. A claim someone else holds is
     refused; talk to them before using `--force`.
   - `git pull`, so the product file holds everyone's locks, invest log and dashboard version.

2. **Settle last week, before pulling this week's data.**
   0. **The Day-1 check of the previous apply, first** (since 2026-10-22; it can also run on its own the day after an
      apply). Read the product's ad spend on the first full US weekday after `<prev>`'s apply and on the US weekdays of
      the 14 days before it (MAP `run_report_sql`, "Day-1 check" below), then:
      `python scripts/autonomy.py day1 --asin <ASIN> --spend <that weekday's spend> --history <s1,s2,...> --date <day> --applied-on <apply day>`
      A trip (`"tripped": true`) opens a "Day-1 spend" item for the book owner and Auto stays on (decision 163): the run
      goes on as usual, and the item goes in the Slack message (step 14.6). Also read back
      anything of `<prev>` not yet read back ("Read back every row"). Skip the rest of step 2 when `<prev>` had no bids
      item.
   - Do it after current execution checks pass (rule 3). There is no calendar delay.
   - Settle `<prev>` before pulling data or planning the next run; resolve any specific execution blocker without a calendar delay.
   - Run folders are not in git. If you don't have `<prev>`, last week's run owner settles it first, or hands you the folder.

   1. Save MAP `list_resources` for `<prev>`'s keywords and targets as `<prev>/live.json`: `sp_keywords` and `sp_targets`,
      `sb_keywords` too when the run has Sponsored Brands rows (`SB bid change`, `SB pause keyword`), and `sd_targets` when
      it has Sponsored Display target rows (`ad_product: SD`, since 2026-10-25), or those rows are always skipped as "not
      found live".
   2. Run:
      `python scripts/dashboard.py approvals --asin <ASIN> --run <prev> --live <prev>/live.json`
      - Do not defer because of the weekday or local hour; act on any specific non-calendar refusal.
      - If it refuses because `payloads/approved/` still holds rows not recorded as applied:
        - if they went out (every row read back), run step 2.4 for them (with the day they went out), then run 2.2 again;
        - if only some went out, record those with `--rows` (step 2.4), then run 2.2 again with `--discard-unapplied`;
        - if they did not go out, run 2.2 again with `--discard-unapplied`.
      - If it refuses with "this run was applied whole on <date>", there is nothing to settle: go to step 3.
      - Read its output. `skipped` and `ignored` give a reason for every row left out. `checked_live: false` means no drift
        check ran.
   3. If it reports `approved` greater than 0 (if it reports 0, nothing was handed out: go to step 3):
      1. Check: `python scripts/dashboard.py applied --asin <ASIN> --run <prev> --folder approved --dry-run`
         If it refuses because of a
         creation already made, don't apply: run 2.2 again with `--discard-unapplied` (nothing went out), and apply what it
         writes.
      2. Apply `<prev>/payloads/approved/*.json` (not `rows.json`) through MAP, in the order of map-playbook.md, and
         read every row back ("Read back every row" below).
   4. Only after 2.3.2 went through, straight away:
      `python scripts/dashboard.py applied --asin <ASIN> --run <prev> --folder approved --date <day>`
      Skip it when nothing was applied. It can't tell: it records whatever `approved/rows.json` names (it says "Nothing to
      record" only when the folder holds no rows at all). If the apply stopped part way, add
      `--rows "<row_id>,<row_id>"` with only the rows that went out ("Read back every row", step 4).
   5. If step 2.4 recorded rows, or step 2.2's `no_payload` lists a `Stop-loss review`:
      `python scripts/log_invest.py --asin <ASIN> --run <prev> --date <day>`
      A promotion's stop-loss clock starts on the day the record gives it. An approved stop-loss review steps its search
      down (step 9).

3. **Pull this week's raw data** into the new `<run>` folder, per [data-pull.md](data-pull.md). First run
   `python scripts/write_window.py check`: on `hold`, wait until its `safe_from` (decision 152: a read in the hour after
   a Scale Insights switch can catch bids on both sides of it). This comes after step 2,
   so the data can show what step 2 sent.
   - Include `campaigns.json`, `recent_kw.json` and the Rank Radar pages (`radar_p*.json`); the stop-loss needs them.
   - Include `campaign_days.json` (14 days of the product's campaigns, one row per campaign per day) for the budget check:
     campaigns that run out of budget at an ACOS well under breakeven get a 'Budget step' row, and a step that stopped
     paying goes back ([budget-headroom.md](budget-headroom.md), with the SQL); rank campaigns step up whatever their ACOS
     (decision 174). The weekly leak check reads the same file, and `sb_campaign_days.json` for Sponsored Brands
     (data-pull.md; rulebook 2g, decision 175). Without it the run proposes no steps.
   - For Sponsored Brands video: `sb_campaigns_p*.json` and `sb_kw_perf.json`, then `sb_keywords_p*.json` for the campaign id
     groups the planner lists in `need_sb_keywords.json` (every consumer SB campaign of the product since 2026-10-25: the
     older ones are priced too, cut only).
   - **The live inventory, every run** (since 2026-10-25, decision 135; data-pull.md, "Live inventory"):
     `live_keywords_p*.json`, `live_targets_p*.json`, `sd_targets_p*.json` and `sd_campaigns_p*.json`, so every keyword and
     target is priced, the ones Scale Insights has no 90-day row for included.
   - Include `visibility_inputs.json` ([visibility.md](visibility.md)): full live inventory, zero-delivery daily reports,
     verified eligible time and blockers, current contextual bid recommendations and dated economics. Keep
     incomplete or missing inputs explicit: old activity-only reports cannot prove an idle keyword was tested.
   - Add the lane inputs (data-pull.md, "Inputs for the lanes"): `inventory_cover.json` and, when you have it,
     `soldscope_volume.json`. **While a product's Auto lane is on (every AI product since 2026-10-22), the inventory cover
     file is required:** without it plan.py stops and says to save it (decision 168). `price_change.json` is no longer
     needed: a recent price change holds nothing since decision 168. In shadow a missing file changes nothing.
   - For Growth ([data-pull.md](data-pull.md), "The listing and the daily clicks"): `listing.json`, the live listing, every
     run (without it the For Growth item is weave-ins only and no pass can close); and `clicks_daily.json` only while the
     product file holds no `growth.anchor`.

4. **Save the team's decisions into `<run>`, the same day you plan:**
   `python scripts/dashboard.py reviews --asin <ASIN> --save <run>/reviews.json`
   It writes `{asin, saved_at, entries}`. The planner turns every decline in it into a lock, so the team's "no" reaches
   this week's plan.
   It also saves Growth's "Picked up" and "Copy pushed" clicks on the For Growth item as `<run>/item_statuses.json`, which
   `publish` moves onto the item (step 11 for a shadow product; the applied publish, step 14.5, for an enabled one). A
   dashboard without the status route gives a warning, and the decisions are saved as before.

5. **Plan:**
   `python scripts/plan.py --asin <ASIN> --run <run> --today <day>`
   - Exit 2 means new invest searches need Amazon's suggested bids: fetch them (data-pull.md, step 5), then rerun. The
     consumer ones are listed in `need_suggested_bids.json`; business invest searches in
     `need_suggested_bids_business.json`, each read in the B2B ad group it names (`suggested_bids_business.json`,
     rulebook 9.7). Never copy a consumer suggestion into the business file.
   - Amazon gives no suggestion for a search, or still rate-limits after one retry about 5 minutes later: save
     SoldScope's estimate in `soldscope_bids.json`, write `bid_sources_tried.json` and rerun (data-pull.md). The run
     goes on and prices those searches itself (rulebook section 2, "When Amazon gives no suggested bid"; decision 106).
     Never wait for a person over a missing suggestion.
   - `summary.sb_video.status` not "ok" means the Sponsored Brands keywords weren't read yet: pull them
     (`need_sb_keywords.json`) and rerun before the preview. Since decision 191 (2026-11-05) the planner stops with exit 2
     until they are read (and `sb_targets`, `sb_themes`, `live_ad_groups`): `--accept-unowned` no longer plans past them.
     A product with about 170 SB campaigns has about 3,000 SB keywords in 7 pages of 500; save each page to its file
     as it comes (the tool-results file when the answer is too big to show), never skip them for time.
   - `summary.organic` (rulebook 2g, decisions 143 and 175): the organic share (reported only), the top-10 searches (75%
     of breakeven) and the weekly leak check (SP and SB). A `note` means `sales_daily.json`, `campaign_days.json` or
     `sb_campaign_days.json` was missing: pull it (data-pull.md, budget-headroom.md) and rerun.
     For each search in `radar_missing`, add it to the product's Rank Radar within the DataDive quota (data-pull.md,
     decision 105) and say how many in the run log. A tripped leak check (`leak.tripped`) is the run's own call: its
     pauses go into the log and the Slack message; nothing about it waits for a person, and it holds no Prove-first launch.
   - It stops with `need_live_inventory.json` while a live inventory read is missing: make the reads it lists and rerun.
     When one can't be made, plan with `--partial-inventory "<why>"`; `summary.inventory.partial_reason` records it, and
     the Slack message should say which keywords and targets were not priced this run.
   - It refuses:
     - without `<run>/reviews.json` while the product file holds any bids item, whatever its status;
     - with a `reviews.json` for another ASIN, or one saved more than a day before `<day>` (save it again: step 4);
     - in a run folder that went out or whose approvals were handed out (use a new folder).
   - If the dashboard can't be read, plan with `--no-reviews "<why>"`. Every change that would have gone out or gone to a
     person then waits for a person, and `auto/` is empty. A row the planner holds anyway (Monitor) stays in `held/`.
   - Read the printed summary, and `summary[0]` in plan.json (shadow or enabled, lane counts, `apply_after`, `stale_reason`,
     `stock_reorder`, `onboarding_reason`, `program`). On an Auto product a missing inventory file stops
     plan.py with what to pull again (decision 168): pull it and plan again. `sqp_age_days` is the SQP's age: write it in
     the log, never wait for a newer week (decision 172). In shadow a `stale_reason` holds every change (Monitor); a
     `stock_reorder` adds the separate manual inventory item without holding Auto rows (step 14.6). An `onboarding_reason` is information only since
     2026-10-22. `planned_invest_month` is the product's planned invest a month once this run's Auto promotions go out,
     and `above_invest_guide` says whether it is above the $2,000 guide (`auto.invest_guide_month`). `program` is the
     program total: the planned invest of every other product file (`other_month`, from each file's `planned_invest`,
     which `log_invest.py` records; a file without one counts its invest log at the standard budgets) plus this product's.
     `over_invest_band` lists the Auto promotions that go past the product's investment band (`invest_band_month`), and
     `over_loss_line` those modelled to lose more than the $60 line for one search (`loss_line_month`). All of these are
     information only (Kim, 2026-10-22, decisions 99 and 100: "we don't want to put a cap and hamper the autonomous
     engine"): no row is parked for money; a person who finds the spend overboard declines on the dashboard or switches the product's
     Auto off. `repromote_cooloff` lists the searches held from re-investment (step 9).
   - **The For Growth step** ([for-growth.md](for-growth.md)). On every run `plan.py` writes `<run>/growth.json` and sets
     `summary[0].growth_trigger` (`first_pass`, `evidence_pass`, `ceiling_pass`, `rotate_out_flag`, `new_skc` since decision 167, or null). For an
     enabled product whose pass is due, `plan.json`'s `human_review` also holds the new `for-growth` item (a stored one is
     carried as it is). There is nothing to approve and nothing to apply: it is not a Needs-human item, not a "For
     human" line, and no run writes it to Amazon (Growth pushes the copy; decision 98's autonomous apply covers the plan's
     change rows, not review items). Put the trigger (or "none"), the anchor and the next-pass window in the run log
     (step 14.3). The rotate-out
     rows need the product file's `relevance.roots` and this run's `listing.json`. A product in the launch stage plans
     nothing, so it has no `growth.json`.
   - **The data stage** (rulebook section 10). `summary[0].stage` says launch, early or mature, and why (`reason`).
     - Launch: the plan stops with "<ASIN> is in the launch stage ...". Build the launch list (onboarding.md) and carry the
       product by hand until it has 10 SQP queries.
     - Early: a promotion's reason can name the stage ("early SQP: seen in one SQP week only", held until its second week
       since 2026-10-22) or the search-term fallback (a Prove-first test that goes out on its own since decision 107).
     - Any stage: a one-word or an unlisted search sends a promotion to a person (rulebook 10.3, item 4).
     - Each reason is in needs-human.md.
     - Put the stage line in the run log (step 14.3).
   - **A volatile week.** `summary[0].volatile_week` has text, at any stage, when this run's SQP added more of our clicks
     than all the weeks before it (against the `sqp_history` in the product file). In stage early, every promotion is held
     (Monitor, since 2026-10-22; it went to Needs human before) with that text as its reason, and a steadier week releases
     it; on a mature product the text is reported only (rulebook 10.4). The run log says "volatile week" either way. A person
     may judge the week real. Only if they say so, plan again
     with `python scripts/plan.py --asin <ASIN> --run <run> --today <day> --allow-volatile`: the text then sits in
     `summary[0].volatile_week_overridden`, and the run log says the hold was lifted, by whom and why. Never lift it on
     your own.
   - **Seasonal products** (a `season` block or `"mode": "harvest"` in the product file; [rulebook.md](rulebook.md)
     section 8). Check the phase first: `python scripts/season.py phase --asin <ASIN> --today <day>`.
     - In the asleep, last mile, off and review phases `plan.py` plans nothing and says so: do that phase's dated step
       (the product file's open items) instead.
     - `summary.season` shows the phase, the next one and its date. A `switch` is applied like any run since 2026-10-22 (it
       sent every change to the book owner before). Once the switch's changes are applied, set `season.phase_applied`
       to the new phase in the product file, in the same commit as the run log.
     - In a rank build, check `over_invest_cap`: the invest budgets can pass the block's cap.
   - Review the visibility report alongside, not instead of, role pricing. Same-query IDX without its benchmark
     remains unknown. Inspect delivery after seven eligible days; a 14-day trial is a proposal default, not an
     automatically launched test. Each proposed target needs concrete bid/spend/loss limits and explicit approval.
   - Sanity-check anything odd before showing it:
     - a large invest list;
     - many bids moving more than 50%;
     - an empty input count;
     - a harvest default bid far from last week's.
   - Planning again in the same folder is fine until something goes out (rule 8). After you write `human_review.json` (step
     10), or fix an input, run it again. If the day has changed since step 4, save the decisions again first.

6. **Live checks** ([live-checks.md](live-checks.md)). Every week:
   - the blacklist rescue: `summary.blacklist_rescue.checked` must be true. If not, read the product's lists into
     `<run>/si_blacklist.json` and plan again (scale-insights-playbook.md, "Blacklist rescue"). A step-95 "Scale Insights
     setup" row lists the entries to take off so no invested search sits on the blacklist;
   - (b) self-blocking negatives in the invest SKCs, the business owners' ad groups and the ad groups new B2B exact
     keywords go into, all listed in checks.json;
   - (c) `recent_kw.json` folded in by the planner;
   - (a) reuse rows;
   - (f) visibility and eligibility blockers and full effective-bid exposure before any proposed delivery experiment.

7. **Harvest review.**
   - Harvested keywords live in the "Harvest Exact - SI import" campaign and are already priced in the plan by
     role.
   - In your summary, say what was harvested since last week and what each became: promoted to its own SKC,
     priced, or negated.
   - Irrelevant harvests go into the negative audit.

8. **Negatives.**
   - Run `amazon-negative-keyword-audit` for the product (7- and 30-day waste, relevance gate, rescue and
     hygiene).
   - Its approved table is applied with the plan.
   - Never negate an invest search or a close variant of one.

9. **Stop-loss: the run steps the search down itself** (Kim, 2026-10-22, decision 98: "the AI applies stop-loss
   step-downs itself and notes them"). Where a logged search shows no organic gain at a stop-loss checkpoint (months 3,
   6, 9 and 12 of investing, against the last checkpoint's reading: organic rank from Rank Radar and organic purchases,
   decision 142; a seasonal rank build at its 2 and 4 weeks; a B2B search: orders and ACOS after 4 weeks), the planner
   writes the step-down (`scripts/stop_loss.py`,
   step 8 on the page): its owner keyword back to its breakeven (a 'Bid change', role Hold) and its campaign's top of
   search back to 0% with the $5 Hold budget (a B2B campaign keeps its budget, and its top of search only drops when no
   other business invest is left in it). Both rows carry `stop_loss_step_down` and the reason ("invested 96 days (the month
   3 checkpoint) with no gain since its start in organic rank (40 -> 41) or organic purchases (0 -> 0)"), go to Auto and
   out with `auto/`. A search with a gain passes: `log_invest.py` keeps that checkpoint's reading for the next one.
   - A row the plan already has on the owner keyword (its index slipped, or it pauses) is marked as the step-down instead
     of a second row, and a budget step on the campaign is dropped. `plan.json` → `stop_loss[]` says `step_down`:
     `written`, `nothing to write` (already at Hold) or `review`.
   - **`review`: a 'Stop-loss review' row for a person** only where no step-down can be written (the owner keyword isn't
     in the run's keyword report) or neither organic rank nor organic purchases can be read (no Rank Radar for the search,
     no SQP row or no baseline). The book owner approves it on the Bids card; `approvals` records it in
     `payloads/approved_decisions.json`, and the step-down is done by hand.
   - **The search leaves the invest log** once the step-down is recorded as gone out, from any folder (`log_invest.py`), or
     on an enabled run whose step-down had nothing to write, or when a person approved its review or sent a cut or pause on
     it (`approved/`, `review/`). An invested cut that went out from `auto/` is not a step-down: the search stays logged,
     its spend still counts in the product's planned invest, and its stop-loss decides.
   - Note it in the run log and the Slack message ("Stop-loss step-downs: 1 search back to Hold").
   - **The cool-off** (Kim, 2026-10-22): for 8 weeks after a step-down (`auto.repromote_cooloff_days` 56, from the
     search's `invest_history` entry) the Auto lane doesn't invest in that search again; a promotion or Invest raise of it
     is held (Monitor, "stepped down at stop-loss on <date>; held from re-investment until <date>"), not parked for a
     person. After the window it is judged on the ladder as usual.

10. **Placements and Needs human, then the preview.** The AI finishes its own research in this run,
    without asking anyone (Kim, 2026-10-22, decision 97): for every listing or price item still in
    research, complete `market-research.md` (query relevance, sufficient-data IDX × search volume, live
    Amazon results, comparable offers and an AI assessment), save `<run>/market_review.json` and rerun
    `plan.py`. People see only decisions: an item reaches the preview and the dashboard when the AI has
    finished and the call is one it can't make itself (a listing, image, offer or price change) or a
    borderline one. (The For Growth item is not a decision but Growth's work order: it is published whole
    for the For Growth tab and gets one line in the preview, below; needs-human.md, "Kind growth".)
    Research the AI could not finish (say Amazon was unreachable) and items it only
    monitors are never shown to people; they stay in the product file and the next run finishes them.
    Note them in the run log for the AI, not in the preview. Broad-intent weakness alone is not a
    listing defect. No automatic price changes.
    Pull `placement_inputs.json` and follow
    `placements.md`. Review every campaign's TOS/product-page/rest-of-search recommendation or hold.
    Use mature windows and current settings/economics. No thin-data boosts, ASIN-to-campaign transfer,
    simultaneous base/placement experiments or automatic +50%/+30% outside rank campaigns. Placement
    suggestions are not executable payloads; obtain separate explicit approval and re-check all
    effective-bid settings.
    **Since 2026-10-26 (decision 140) `placement_inputs.json` is needed every run, not only for the review:** the
    product-page base bid (placements.md, "Product-page base bid") shapes a campaign only from it, and the down-only rows
    (placements.md, "Down-only bidding") go to a person for any campaign whose product ads it does not show. Build it
    before `plan.py` (data-pull.md, "Economics"); without it, `summary.placement_shape` says "not shaped: no
    placement_inputs.json" and every down-only row waits for a person. Both write in the Auto lane: `5b_bidding_strategy.json`
    after the campaign updates, `9c_placement_shape.json` last, only for campaigns whose bids all read back
    (map-playbook.md, steps 10 and 16).
    **Rank launches (Kim, 2026-10-20 SGT):** top of search on a rank-investment campaign (+50% Invest,
    +30% Prove first, `placement.rank_tos_standing`) is standing policy. A new rank campaign launches at it,
    and a live one is set to it, with no separate approval, as long as the promotion passes the evidence
    ladder (rulebook 7; its investment band is information since decision 100, and there is no money level since
    decision 99, 2026-10-22); otherwise the row waits in Needs human as any promotion does. A live rank campaign whose only change is top of search to the policy
    (`policy_tos_only`, budget unchanged) is judged the same way; since 2026-10-22 a budget change at the role's
    standard budget applies on its own too, and since 2026-10-23 (decision 107) a non-standard budget or boost is written
    at the standard (`budget_overrides` being the standard for its search). Check each row's
    `tos` / `tos_now` and `other_placements` in the plan, and the live campaign again at apply (MAP, before the
    write). A campaign the policy leaves alone says why in its `placement_note`.
    These restrictions describe the placement-economics track, not a veto on explicitly proposed
    rank investment. Check `proposed_rank_experiments` in product state, reassess relevance and early
    search evidence, and retain or explicitly propose removing each experiment with reasons. Display
    it separately from placement-proven suggestions; thin placement evidence must not silently zero
    a rank experiment. Kim restored 30 proposals on Oct 18 and subsequently approved the five-ASIN execution
    list. Use each product's dated approval and verified execution record: some are live and others retain setup or
    delivery holds. Never infer launch status from the proposal date, reset an existing stop-loss clock or expand an
    allowance because this run adds a delivery review.
    Review `plan.json` → `human_review` and follow
    `needs-human.md`. Every sweep assesses listing conversion gaps and price positioning. Add dated,
    evidence-backed LLM findings in `<run>/human_review.json`, then rerun the planner. Keep thin data out
    of conversion diagnoses. Price increments/decrements need comparable-pack evidence, refreshed
    economics, a test review/rollback and Kim approval; never execute a price change from this queue.
    Include these human decisions in the run's "For human" items (step 14.6).

    **Preview (only for a shadow product, or when a person asks to see one).** An autonomous run has no proposed step: it
    applies its Auto rows (step 12) and publishes the result as applied (step 14.5). For a product whose Auto is off:
    `python scripts/preview.py --out <run>/preview.html <run>/plan.json --date <day>`
    - Each row's Why (Evidence for a promotion) ends with its lane: "Lane: applies automatically" (in shadow "would apply
      automatically (shadow run)"), "Lane: waits for a person" or "Lane: held" (an old plan's row flagged
      `past_kim_level`, from before decision 99, still adds " · past Kim's $600 level"; no new plan carries the flag).
      A capped raise shows the bid that is written. A held row says "held: not in this apply".
    - Publish the page as an Artifact. Message:
      - what changes, and how many rows are Auto, Needs human and Monitor (in shadow: that nothing applies on its own);
      - planned investment vs last week;
      - harvest and stop-loss items;
      - delivery gaps versus low demand/CTR/CVR or setup blockers, and any separately costed learning experiments;
      - anything you adjusted after live checks.
      - the For Growth line, if the run raised an item (the pass tag and the due date). The preview gives it one line, not a
        tile, and it needs no approval.
    - Then update the product file's `brief` and `open_items`.

11. **Shadow products only: publish the proposal to the dashboard:**
    `python scripts/dashboard.py publish --asin <ASIN> --run <run> --state proposed --date <day> --by "<name>"`
    (dashboard.md). The page then shows the run as waiting for approval, and a Bids item in Needs human, one item per ASIN.
    An enabled run skips this step: it publishes once, as applied (step 14.5), and its Bids item (only the rows parked for
    a person, none when nothing is parked) goes up with that publish.
    - A publish supersedes `<prev>`'s bids item. Its approvals can no longer go out (decisions-only mode); approve those
      rows on `<run>`'s item.
    - Every publish (this one, or an enabled run's applied publish, step 14.5) also does the For Growth work
      ([for-growth.md](for-growth.md), "Lifecycle"). It stores the run's gate
      counts and, when the product file has none, its anchor (from `growth.json`); moves Growth's saved clicks
      (`item_statuses.json`) onto the item; and resolves a picked-up or pushed item when `listing.json` shows the copy
      changed against the item's snapshot, with an activity line ("For Growth: listing change seen ..."). It changes the
      product file (`growth`, `human_review`): commit it with the run (step 14.8).

12. **Enabled products: apply `auto/` yourself,** during the audit, including weekends, with no per-run
    approval (decision 98). In shadow, `auto/` is empty: skip this step.
    1. Check the clock: `python scripts/write_window.py check`. On `hold` (a Scale Insights ON switch is under 2 hours
       away, decision 151, or under an hour past, decision 152), don't write yet. Either wait and do this step again from
       its `safe_from` time (never more than 3 hours away), re-reading live state first, or, if the session can't wait,
       park the folder:
       `python scripts/write_window.py park --asin <ASIN> --run <run> --folder auto`. That adds a dated open item
       ("Apply held auto rows after HH:MM SGT") that the morning routine lists under `checks`; it is done by re-reading
       live state and doing this step 12 again. A parked folder is not a failure: say it in the run log and the Slack
       message as "held until <time> (Scale Insights switch)". The same check comes before `review/` and `approved/`.
       Then: `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder auto --dry-run`
       If a non-calendar guard refuses, resolve the stated issue; do not substitute a Monday wait.
       If it refuses because the product's Auto is off (a guard tripped since the plan), don't apply: the rows wait. If it
       refuses because of a creation already made since the plan, don't apply: go back to step 4 (the folder may be
       planned again, since nothing of it went out).
    2. Re-check live state first (live-checks.md): read the folder's keywords, targets and SB keywords with MAP
       `list_resources` into `<run>/prewrite.json` and run
       `python scripts/write_window.py prewrite --run <run> --folder auto --live <run>/prewrite.json`.
       `apply` (exit 0): go on. `replan` (exit 4): only Scale Insights' dayparting switch moved bids since the plan.
       That is expected (decision 152): don't stop, don't ask, don't call it drift; plan again from a fresh read once
       `check` says ok. `stop` (exit 5): a bid changed some other way; say so before applying (AGENTS.md rule 1).
       Then apply `<run>/payloads/auto/*.json` (not `rows.json`, not `scale_insights_steps.json`) through MAP, in the order
       of map-playbook.md. After each write step, read every row back and stop on any mismatch ("Read back every row"
       below).
    3. Do the folder's `scale_insights_steps.json` in the signed-in browser (Claude in Chrome, or Playwright for Codex),
       one entry at a time, as [scale-insights-playbook.md](scale-insights-playbook.md) says (the entry's `how` names the
       page), and re-read each page after saving. A step the browser can't do (signed out, the page won't load, Scale
       Insights hasn't synced the campaign yet) is not done: leave its row out of the record (12.4) and add it to the "For
       human" items for the book owner (step 14.6). Never type a password: a person signs in (AGENTS.md rule 5).
    4. Only after 12.2 and 12.3 went through, straight away:
       `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder auto --date <day>`
       If anything stopped part way, add `--rows "<row_id>,<row_id>"` with only the rows that went out and the Scale
       Insights steps done ("Read back every row", step 4).
    5. Straight after: `python scripts/write_window.py after-apply --asin <ASIN> --run <run> --folder auto`. When a
       switch comes within 4 hours of the write, it adds a dated open item ("Re-check auto bids after the HH:MM SGT
       switch"); otherwise it adds nothing. To do that item (the morning routine lists it, or do it in the session once
       the time has passed): read the folder's rows back with MAP `list_resources` as in "Read back every row", save
       them as `<run>/recheck.json`, and run
       `python scripts/write_window.py recheck --run <run> --folder auto --live <run>/recheck.json`.
       A bid counts as held when Amazon shows the written bid or the written bid times the hour's modifier. When it
       lists rows (`reverted`), send the rows of its `resend` file again through MAP, each group with the same call as
       the payload file it names (they are the same, already-recorded rows, so no new approval and no new `applied`),
       read them back, then mark the item done with a log line ("Re-check: N of M bids put back by Scale Insights at
       HH:MM SGT, sent again and read back"). Missing rows (`live` null) are read again before anything is sent.

13. **During the week: apply what the team decided.** Pick one route per run (rule 7).

    **The row-by-row route (`approved/`).** Do this whenever the team has decided rows on `<run>`'s item on the dashboard.
    Do 13.1 to 13.4 back to back, after current execution checks pass (rule 3).
    1. Save MAP `list_resources` as `<run>/live.json` (`sp_keywords`, `sp_targets`, and `sb_keywords` when the run has
       Sponsored Brands rows, as in step 2.1).
    2. Run:
       `python scripts/dashboard.py approvals --asin <ASIN> --run <run> --live <run>/live.json`
       - Run 13.1 to 13.4 during the audit, including weekends.
       - If it refuses because `approved/` holds unrecorded rows, do step 13.4 first if they went out, or re-run with
         `--discard-unapplied` if they did not. If only some went out, record those with `--rows` first (rule 6).
       - If it reports `approved` is 0, there is nothing to apply: stop here.
       - An approval counts only at the row's level: a Kim row needs Kim, an owner row anyone signed (rulebook
         7.10; since 2026-10-22 every bid row is the book owner's or Kim's), and a Lee row (one she declined)
         Lee or Kim. A row a decline holds also needs the decliner's level (Kim when Kim declined, Lee
         when Lee did; rulebook 7.8), the highest-ranked decliner's when several declined. A wrong-level approval
         is listed under `skipped`, with the reason. So is an approval on a row a rank experiment holds ("a rank
         experiment holds this search until its review").
    3. Check, then apply:
       1. `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder approved --dry-run`
          If it refuses because
          of a creation already made, don't apply: re-run 13.2 with `--discard-unapplied` and apply what it writes.
       2. Apply `<run>/payloads/approved/*.json` (not `rows.json`) through MAP, and read every row back.
    4. Only after 13.3.2 went through, straight away:
       `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder approved --date <day>`
       If the apply stopped part way, add `--rows "<row_id>,<row_id>"` with only the rows that went out ("Read back every
       row", step 4).

    Run `approvals` before any `dashboard.py review --asin <ASIN> --id bids-<date> --status resolved|dismissed --note "<why>"`
    on the bids item. A resolved item's approvals still go out; a dismissed item's don't.

    **Instead: the whole-run route (`review/`).** Use it only on Kim's explicit whole-run yes on the preview, and only
    while nobody has decided a row of `<run>`'s item. Do it after current execution checks pass.
    1. Check: `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder review --dry-run`
       It refuses while the item has any decision ("apply
       approved/ instead"), when a row of `review/` was declined on the dashboard after the plan (go back to step 4 and plan
       again), or when it would create a search already created. If it refuses, don't apply `review/`, and tell the team
       which rows it names.
    2. Apply `<run>/payloads/review/*.json` (not `rows.json`) through MAP, and read every row back. Check and apply back to
       back: a decision made between them goes out.
    3. Only after 13-alt.2 went through, straight away:
       `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder review --date <day>`
       If it now refuses (a decision landed since the check), run it again with `--record-anyway` and report the rows it
       named: they went out against a decision. If the apply stopped part way, add `--rows "<row_id>,<row_id>"` with only
       the rows that went out.

       After this, `approvals` refuses this run ("applied whole").

14. **Record, publish and tell the team** (right after step 12 on an enabled product; at the end of the week for a shadow
    one).
    1. Save the decisions again into the run folder, so the applied page can show declines:
       `python scripts/dashboard.py reviews --asin <ASIN> --save <run>/reviews.json`
    2. Log the invest searches:
       `python scripts/log_invest.py --asin <ASIN> --run <run> --date <day> [--applied-harvest-bid]`
       A week where nothing was recorded as applied starts no clock. A search leaves the invest log only by a step-down on
       record (step 9). It also records the product's `planned_invest` (its planned invest a month after this run), which
       the next runs of every product add up for the program total (information only).
    3. The run log: `logs/<date>-<product>-weekly-run.md` in the your-ppc-repo repo (logs/README.md). Date every figure;
       include change set IDs, the read-back result, and the reasons for anything not applied.
       - **The stage line**, from `summary[0].stage`: `stage: early (21 observed days, 13 trusted queries)`. When the stage
         changed since last run, say so: "stage early -> mature: 28 observed days, 13 trusted queries".
       - **A volatile week** ("volatile week: the SQP since <baseline date> (through <this run's date>) added <n> of our
         clicks"). Early: say it held the
         promotions, or that `--allow-volatile` lifted the hold, who decided and why. Mature: say the week was volatile and
         nothing was held.
    4. The product file: one dated `activity` line per applied change set, done `open_items` marked done, a fresh `brief`.
       Write `<run>/applied.json` if the apply deviated from the plan. Update `monitor` (last 30 days, Scale Insights
       `get_sales_data`; dashboard.md).
    5. Publish what went out:
       `python scripts/dashboard.py publish --asin <ASIN> --run <run> --state applied --date <day> --by "<name>"`
       Only rows in `payloads/applied_rows.json` read applied. A week where nothing was recorded marks none applied. The run
       shows as "Just changed" and on the optimisation map, and is logged in the team's activity feed.
       Then record the run in the product file (rulebook 10.6), once the run folder is planned for the last time:
       `python scripts/dashboard.py refresh --asin <ASIN> --run <run> --note "<one line>"`
       It appends the run's SQP totals to `sqp_history` (next week's baseline for the volatile-week check) and sets
       `data_stage` to the run's stage (a recorded "mature" stays), and stores the run's For Growth gate counts
       (`growth.candidates`) from `growth.json`; it does not move Growth's clicks or close a pass (only `publish` does).
       `--dry-run` first shows what it would record. Run it
       after the last plan of the folder: a re-plan after it would find this week's own totals as its baseline and, in
       stage early, lose the volatile-week hold (in mature the hold does not apply, so only the summary's text would go).
       It republishes the page from the product file, keeping the run's tables. Commit the product file with the run log
       (step 14.8).
       An enabled run publishes `--state applied` with no proposed publish before it, and needs no approval for it
       (decision 98). Its page carries the run's Bids item only when something is parked for a person.
    6. **"For human" and the Slack message** (Kim, 2026-10-22: "letting the humans know what it did"). Every run that
       applied, planned or parked anything gets one message in #3d-ppc-standup (C0EXAMPLE01):
       - When `summary[0].stock_reorder` is set, first put the "reorder stock" item on the product page:
         `python scripts/autonomy.py stock --asin <ASIN> --run <run> --date <day>` (an open "decision" entry for the book
         owner; once a day).
       - Build the message: `python scripts/notify.py --asin <ASIN> --run <run> --date <day>`. It prints
         `{channel, channel_id, text, mentions, owner}`: a recap of what went out tagging the book owner (bids cut and raised,
         rank campaigns and their $/day, stop-loss step-downs, pauses and negatives, budgets, Scale Insights steps done, what
         was held and why, in a few words; counts and money only, no research text; "Planned invest $X/month (above the
         $2,000 guide)" when the plan is above the guide, "Past the product's $X/month invest band: <searches>" and
         "Modelled to lose over the $60/month line for one search: <search> ($X/month)" when an Auto promotion is past
         them), the dashboard link, and a "For human" section only when something
         is parked, one line per item tagging who decides: Kim for a price and Scale Insights beyond the standard setup;
         Lee for a listing, image or offer change or cutting a product; the book owner for the rest (a one-word or
         unlisted search's promotion, low stock, Auto switched off by a guard). Nothing is parked for money (decision 99),
         and no bid or rank call (decision 107).
         A run that applied and parked nothing still gets its one-line "No changes this run."
       - A Scale Insights step the browser couldn't do (step 12.3) is not in the plan's parked rows: add a line for the book
         owner to the text before posting ("- <@owner> Scale Insights: <what> not done: <why>; please do it in the web app").
       - Post `text` to `channel_id` with the Slack connector (`slack_send_message`), as it is. This post is part of the
         run Kim approved (decision 98): no per-run OK. Never post anything else to Slack from a run, except the For
         Growth line below.
       - **For Growth** (Kim, 2026-10-25, decision 124): when the run raised a listing pass, `notify.py`'s output also
         has `growth` (otherwise it is `null`). Post `growth.text` to `growth.channel_id` (#3-marketing-traffic,
         C0EXAMPLE02) as it is. Then on Monday board `growth.monday.board` (9000000011, board 2), find the product's item
         by the ASIN (`text3`), set Status to `growth.monday.status` ("Optimise Listing") first, then move it into group
         `growth.monday.group` ("[GROWTH TEAM] - For Listing Optimisation"; a board automation moves an item set to that
         status into "First Listing Optimization", so the move must come second); with no item on board 2 and `if_missing` `create`, create
         one in that group named `growth.monday.item_name`, ASIN in `text3`, same status. Read it back. Both are part of
         the approved run: no per-run OK. If the group or that status is missing, write it in the run log and leave the
         board unchanged. The
         rules are in [for-growth.md](for-growth.md), "Telling Growth".
       - The book owner comes from the product file's `registry.book_owner`, else config.json `notify.book_owners`, else
         the owner column of `docs/sweep-tiers.csv`, else Lee.
    7. Release the claim: `python scripts/dashboard.py release --asin <ASIN> --note "<one line: what was done>"`
    8. Git: commit and push `data/asins/<ASIN>.json` and the log. The product file holds the decisions (decline, approve and
       create locks), `invest_log`, `planned_invest`, `auto` (a guard's kill switch), `open_items`, `human_review`,
       `sqp_history`, `data_stage` and the dashboard version, so teammates' runs start from the same state.
       Run folders are not in git.
       - **An autonomous run commits and pushes as its last step** (design, "What a run does", step 6; decision 98), and
         always when `approvals`, `applied` or `autonomy.py` wrote the product file (rule 10). `git pull` first; push before
         anyone plans the product again.
       - A shadow run: commit and push when the person asks (and only as authorized), and always when rule 10 applies.

    Approvals made on `<run>`'s item after 14.5 are settled at the start of next week (step 2, with `<run>` as `<prev>`).

## For Growth: the anchor and the switch (once per product, 2026-10-22)

Two steps per AI-managed product before its weekly run can raise a For Growth item (the rules and dates are in
[for-growth.md](for-growth.md)). Both change the product file only: commit and push it afterwards (step 14.8).

1. **Anchor, at onboarding** ([onboarding.md](onboarding.md), step 8), and for any AI product that has none. The anchor is
   the later of the Monday launch date (`launch_date` in the product file) and the product's first ad click. Pull
   `clicks_daily.json` into the run folder ([data-pull.md](data-pull.md)), then from the skill folder:
   `python scripts/dashboard.py growth --asin <ASIN> --anchor --clicks-daily <run>/clicks_daily.json`
   It writes `growth.anchor` and `growth.next_pass` and prints the anchor with its source, the first due date (anchor + 56
   days) and the window. `--dry-run` shows it first. To set the date by hand (a launch date that is wrong on the board):
   `python scripts/dashboard.py growth --asin <ASIN> --anchor --date <YYYY-MM-DD> --source hand`. A hand-set anchor stays
   until another `--date`. With no `launch_date` and no click series it stops and writes nothing.
2. **Enable: every AI product (decision 166, 2026-10-29).** The publish (step 14) switches it on by itself for an AI product
   that is off, with `growth.enabled_on` the publish date, unless a person turned it off with `--disable` (that stays
   off). To do it by hand, first check that the product file has `relevance.roots` (without roots the block has no rotate-out
   rows and no flags). Then:
   `python scripts/dashboard.py growth --asin <ASIN> --enable --by "<name>"`
   It sets `growth.enabled`, adds an activity line and prints the window. `--disable` turns it off. From the next weekly
   run (step 3 on), the first block is raised on the first run on or after the first due date.

As of 2026-10-29 every AI product is enabled. A block off-cycle, for Lee or Kim on any day, is `growth --asin <ASIN> --run
<run> --emit` ([for-growth.md](for-growth.md), "Commands"); it merges into the product file and never publishes.

## Read back every row

After each MAP write step (the order is in [map-playbook.md](map-playbook.md)), read back every row of that step, not a
sample. This covers every folder you apply.

1. Read the rows with MAP `list_resources` (`sp_keywords`: one campaign per call; `sp_targets`: by `target_id`;
   `sb_keywords` when the folder holds Sponsored Brands keyword rows, `8_sb_keyword_updates.json`; `sb_targets` by
   `campaign_id` when it holds `8b_sb_target_updates.json` (decision 155); and `sd_targets` by
   `campaign_id_filter` when it holds `9b_sd_target_updates_NN.json` (since 2026-10-25): without them those rows read back
   as mismatches). Save the output to `<run>/readback.json`. A list, or `{"data": [...]}` or `{"results": [...]}`,
   both work.
2. Compare it with what was written. From the skill folder, in `python`:

   ```python
   import sys, json, glob
   sys.path.insert(0, 'scripts')
   import lanes, dashboard
   run = '<run>'
   written = [row for f in sorted(glob.glob(run + '/payloads/auto/*.json')) if not f.endswith('rows.json')
              for row in json.load(open(f)) if row.get('keywordId') or row.get('targetId')]
   live = dashboard.read_live(run + '/readback.json')
   import daypart_base
   print(lanes.readback_mismatches(written, live, daypart_base.modifiers(dashboard.config())))
   ```

   Use `approved/` or `review/` in place of `auto/` for those folders. `[]` means every row reads back as written.
3. `readback_mismatches` covers keyword and target bids and pauses. A bid differs by more than $0.005; states compare
   without regard to case. A row it can't find or can't read counts as a mismatch. Campaigns, negatives and creations are
   checked as map-playbook.md "Verify after each step" says.
4. **On any mismatch, stop.**
   - Write no more rows of the folder.
   - **Record exactly what went out, and nothing else:** the rows of the earlier write steps and the rows of this step that
     read back as written. The folder's `rows.json` lists, for each payload file, the row id behind each payload row, in
     order. Then:
     `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder <folder> --date <day> --rows "<row_id>,<row_id>"`
     It refuses a row id the folder's `rows.json` doesn't hold and writes nothing. Never run `applied` without `--rows`
     for this folder: it would record every row, including rows never written. Write in the run log what went out and what
     didn't.
   - **Never discard a folder that partly went out.** Record what went out with `--rows` first. For `approved/`, the rows
     that did not go out are then discarded with `approvals --discard-unapplied`: it hands out only the rows not recorded,
     and a recorded creation never comes back (its create lock). Don't apply them again until the mismatch is understood.
     For `auto/` or `review/`, the rest waits for next week's plan. The folder itself is never applied again: its check
     (`--dry-run`) refuses it ("this folder partly went out on <date>").
   - **A Sponsored Brands video build that stopped part way** (the campaign was made, a keyword failed): record what went
     out with `--rows`. `applied` create-locks the whole build and lists the rest under `add_by_hand` ("add these keywords
     by hand to the campaign that now exists (<campaign name>)"): add them to that campaign with MAP `sb_keywords` create,
     read them back, and never apply the build again.
   - **The comparison for `auto/`** is
     `python scripts/autonomy.py readback --asin <ASIN> --run <run> --folder auto --live <run>/readback.json --date <day> [--skip <ids>]`
     (dry-run it first). Since 2026-10-29 (decision 163) it reads every saved shape (a plain list, items/data/results,
     MAP's text wrapper), leaves out `--skip` ids (rows held by hand and never sent), and stops with an input error,
     writing nothing, when half or more of the rows are missing from the file (a wrong shape or a missing read: read again).
     A real mismatch returns `stop: true` and opens a "Read-back" item for the book owner; Auto stays on. Send those rows
     again through MAP, read them back, and record only what reads back (`applied --rows`).
   - With `guards.readback_switch_off` true (the rule before) a mismatch writes `"auto": {"enabled": false}` instead; then
     `applied --folder auto` records only with `--record-anyway`, and turning it back on is Kim's.
   - The run's Slack message (step 14.6) carries the item for the book owner.

## Day-1 check (24 hours after an apply)

- **Price.** If changed: SP-API `amazon_get_competitive_pricing` shows the new buy-box price. MAP's
  `get_listing_change_history` verification lags; don't wait on it.
- **New campaigns.**
  - Scale Insights has synced them: SI `get_campaign_settings` with the IDs no longer lists them under
    `missingCampaignIds`.
  - They carry 302497 or 302498, nothing with bid rules (Assigned rules page).
- **Self-blocking negatives.** None reappeared in the invest SKCs after SI's nightly run (live-checks.md, check b).
- **Scale Insights' stored bid, for every row written.** MAP read back the bid Amazon holds. Scale Insights keeps its own
  copy, and it can differ (the 2026-10-17 drift above).
  - Read SI `get_keyword_performance` (and `get_target_performance` for targets): `asin_list=[ASIN]`, `days=30`,
    `mode="raw"`, as in data-pull.md. Each row's `KeywordId` and `Bid` are the stored weekday bid.
  - Compare every row of the folders that went out (the folders' `rows.json` name them) with the bid written. Save the raw
    SI rows as `<run>/si_bids.json` and check the field names in them first.
  - **The 202 Brake is not drift.** It cuts 30% a week (floor $0.10) on 26+ clicks and no orders, which is exactly the
    keywords the planner cuts (SKILL.md rule 1). A stored bid below the written one and at or below the written bid × 0.7
    (or at or below $0.10) is the Brake's work, not a mismatch. From the skill folder, in `python`:

    ```python
    import sys, json, glob
    sys.path.insert(0, 'scripts')
    import lanes, dashboard
    run = '<run>'
    folders = ['auto']  # the folders that went out this week
    written = [row for d in folders for f in sorted(glob.glob(f'{run}/payloads/{d}/*.json')) if not f.endswith('rows.json')
               for row in json.load(open(f)) if row.get('bid') is not None and (row.get('keywordId') or row.get('targetId'))]
    stored = [{k: v for k, v in (('keywordId', r.get('KeywordId')), ('targetId', r.get('TargetId')), ('bid', r.get('Bid')))
               if v is not None} for r in dashboard.read_live(run + '/si_bids.json')]

    def braked(m):  # a stored bid the 202 Brake cut: below the written bid, and at or below x0.7 of it or $0.10
        try:
            w, s = float(m['written']), float(m['live'])
        except (TypeError, ValueError):
            return False
        return s < w and s <= max(w * 0.7, 0.10) + 0.005

    print([m for m in lanes.readback_mismatches(written, stored) if not braked(m)])
    ```

    `[]` means every stored bid is the written one, or the Brake's. Name the braked rows in the run log.
  - A keyword with no activity in the last 30 days doesn't show in SI's data. Say so in the run log: it can't be read back
    this way.
  - A mismatch is handled as in "Read back every row", step 4. Don't fix it with an SI change set unless Kim says so: on
    2026-10-19 six stored bids were fixed that way, with his explicit OK.
- **The 24-hour spend check.** After any apply, compare the product's ad spend on the first full US weekday after the apply
  (Los Angeles date) with its average ad spend on US weekdays over the 14 days before the apply.
  - Get daily spend from MAP `run_report_sql` (the product's campaigns carry the ASIN in their name; `describe_report_tables`
    gives the column names).
  - From the skill folder, in `python`:

    ```python
    import sys
    sys.path.insert(0, 'scripts')
    import lanes
    lanes.spend_check(next_weekday_spend, last14_weekday_spends)  # a number, and a list of the earlier weekdays' spends
    ```

  - **True means the spend is over 1.5 times the average** (2026-10-19, spec section 6). Since 2026-10-22 run it as
    `python scripts/autonomy.py day1 --asin <ASIN> --spend <spend> --history <s1,s2,...> --date <day> --applied-on <day>`
    (step 2.0): a trip opens a "Day-1 spend" item for the book owner, Auto staying on (decision 163; `guards.day1_switch_off`
    true restores the switch-off), and the next run's Slack message carries it. The morning routine runs it the day after an apply
    (SKILL.md); the skill never creates a schedule for it.
  - An empty history gives False (nothing to compare with). A spend that is NaN or infinite gives True, and a negative one
    raises an error.
  - In shadow there is no auto lane to switch off. A trip there is a note for the book owner: the jump came from rows a person
    approved.
- **Spend vs plan.** Use the reporting timezone/window returned by the source and allow for reporting and conversion
  lag. Day 1 is a setup/delivery check, not mature profitability evidence. Read current approved SI schedules and
  direct overrides before interpreting zeros. The old weekend 05:00–06:59 limitation is not a current general rule:
  shared rule 203 was widened on Oct 17, while some groups retain legacy overrides. Record human-facing times in
  SGT and normalize source dates; do not silently change schedules to make a test deliver.
- **Out-of-plan keywords.** Flag unexpected exposure above modeled breakeven for review, accounting for approved
  rank/learning allowances, placement/dynamic settings and actual CPC. A high base bid alone does not prove loss.
- **Learning follow-through.** Check spend/loss limits without waiting for mature attribution. Review conversion
  once the source's attribution window is sufficiently mature. A missing or blocked delivery check cannot reset
  an experiment, restart its allowance or silently extend the default 14-day trial. No background worker or
  follow-up schedule is created by the planner.

## Cadence for the team

- **Weekly:** rebid, harvest review, stop-loss.
- **Weekly or fortnightly:** negative audit, per that skill.
- **Monthly:** price check against best-selling same-size packs; economics refresh (`profit_per_unit`).
- **At months 3, 6, 9 and 12 per invested search (2 and 4 weeks on a seasonal rank build; 4 weeks for a B2B invest):**
  the stop-loss, judged on organic rank and organic purchases only (decision 142), its step-down applied by the run itself
  since 2026-10-22 (step 9). Until 2026-10-26 it was at 4 and 6 weeks.
- **The day after any apply:** the Day-1 check (`autonomy.py day1`), at the latest at the start of the next run.
- The Nov 9, 2026 shadow gate (rulebook 7.11) is superseded: Kim turned Auto on for every AI product on 2026-10-22
  (decision 98).
