# AI bidding field guide: situations and what to do

For any agent running `amazon-ppc-ai-bidding` from a pulled copy of the repo: Claude Code on a teammate's
laptop (Alex, Sam, Lee), or Codex on Kim's. That session doesn't have Kim's project memory or his threads; this page carries what they
learned. Written 2026-10-30 (updated 2026-10-31 for decision 174) from the decisions log, the run logs and what the team hit in #3d-ppc. The person's
side is in [run-ai-bidding.md](run-ai-bidding.md); today's rules in plain words, without the history, are in
[rules-today.md](rules-today.md); the why behind the rules (goal, strategy, bid maths, history) is in
[background.md](background.md). Written for both agents: the teammates use **Claude Code**, Kim uses **Codex**.
Everything here applies to both; where the two differ, the section "Claude Code and Codex differences" below says how.

Write to the teammate in plain words: say what happened, what you are doing about it, and, if they must act, exactly
where to click or what to type.

## The standing direction (read this first)

Kim, 2026-10-30, in #3d-ppc and decision 172: "In short, I don't even think we need to have so many safeguards. Why
don't we just go ahead and get the job done?" and "The PPC teammates are independent humans. They also don't need to
ask Kim."

So:
- **Run and apply in as few passes as you can.** Pull, plan, apply the Auto rows, read back, record, publish, Slack, commit:
  one session, no preview to approve for an Auto-on product (decision 98).
- **A real permission denial still stops that action.** Report its exact scope; never route around it with another
  tool (AGENTS.md). That's not a hold you add, it's the tool refusing.
- **Don't add holds, flags or questions of your own.** If the skill's code doesn't stop, don't stop. If an older paragraph
  of the skill says to wait or ask, check the newer decisions below first.
- **The book owner's yes is enough** for anything on their own products that isn't on Kim's short list (bottom of this page).
  Most of it needs no yes at all: it is Auto.
- **Newest decision wins.** `SKILL.md` and the references carry text from Oct 17 onward. When two passages disagree, the
  later one in `docs/decisions.md` wins. The ones that most often contradict older text:

| Decision | Date | What it changed |
|---|---|---|
| 98 | Oct 22 | The run applies its own Auto rows, publishes, posts to Slack and commits. No approval |
| 114, 116 | Oct 24 | Apply during the audit on any day, weekend or night. An "audit" or "re-audit" of an Auto-on product is a normal run |
| 162 | Oct 29 | Each keyword is priced on its own search's SQP conversion |
| 163 | Oct 29 | A Day-1 spend trip or a read-back mismatch opens an alert. Auto stays on |
| 164, 165, 168 | Oct 29 | No raise cap, no +25% step, no price-settle hold, no 10-day SQP stop |
| 169 | Oct 29 | The referral fee is read from settled orders every run |
| 172 | Oct 30 | No readiness audit. Any book owner adds a product. Plan on SQP of any age; seasonal products add last season's SQP. Shared campaigns are excluded by the run itself |
| 174 | Oct 31 | Apply as soon as the run finishes (no 10:00 SGT wait). Weekend dayparting cut is −20% (bids × 0.8). Prove first at 2 orders, counted as the higher of SQP purchases and ad orders. No money cap on validated promotions; rank campaigns that run out of budget step up whatever their ACOS. Low stock (14 days or less) parks increases For human until a person clears it. The referral fee reader fixed (0.15 = 15%) |
| 175 | Oct 31 | Ordinary keywords at 100% of breakeven whatever the organic share (the organic-share brake is gone); top-10 rule 75%; the efficiency guard became the weekly leak check (pauses ordinary no-order keywords only; no bid cut, no Prove-first hold). |
| 176 | Oct 31 | The daily rank refresh is retired: dashboard ranks update when a product's audit runs; a by-hand refresh is llm-handbook 6.10. Don't schedule it again without Kim |
| 177 | Oct 31 | Validated ordinary keywords (Hold with 2+ orders; Test or Discovery with 2+ orders at index 0.8 or more) and launch-test keywords (Test or Discovery with 0-1 orders) bid the **suggested mid**, not breakeven: Amazon's median, else SoldScope's, else an estimate. 75% of it in the top 10. 2+ orders at a high index goes to Prove first even before the search is trusted |
| 178 | Oct 31 | Prove first at **index 1.1** (was 1.25), also for the search-term fallback and the Discovery cap lift. The launch test is sized to the product's ad conversion: it ends at 2 expected orders (15 to 60 clicks; 20 at 10%, 40 at 5%), or 3 with one order (at most 90). The leak check doesn't pause a keyword still in its test |
| 182 | Nov 4 | No rank investment (Invest or Prove first) on a search over **2,400 searches a month** (3,000 since decision 189; the highest of SQP, DataDive and SoldScope): it bids Defend (since decision 183 at its suggested low, never under breakeven). A logged invest search over that cap, or whose index slips under 0.8 on 15+ clicks, steps down at its next run (breakeven, top of search 0%, $5 budget) without waiting for month 3. A "Stop-loss review" row with "decision 182" in its reason is that step-down, held only when the keyword is missing from the report. |
| 183 | Nov 4 | **Every product is on Auto.** The suggested mid is for Sponsored Products **exact** keywords only; broad, phrase, product targets and Sponsored Brands bid breakeven. A search over the rank cap bids its exact keyword at the suggested low (never under breakeven, never raised). A product's own `rank_max_monthly_searches` in its file overrides the cap (a person raises it when the listing has the reviews and variations for bigger searches). |
| 184 | Nov 4 | The skill folder is now `ppc-ai-bidding-audit-2026-11-04` (it was `...-2026-10-31`). A session that can't find the old name: `git pull`, then start a new session. Before and after, in plain words: [whats-new-2026-11-04.md](whats-new-2026-11-04.md). |
| 185 | Nov 4 | The rank cap binds a seasonal rank build too: a season rank search over the cap (2,400 a month then, 3,000 since decision 189) (counting the season curve's peak week x 52/12) bids the suggested low on its exact keyword, not Invest. |
| 186 | Nov 4 | Scale Insights is the default for SQP, keyword, target and search-term reports; when its MCP allowance runs out, SoldScope (SQP) and MarketplaceAdPros (ad reports) are the backup, converted by `scripts/report_sources.py`. Rows on the overnight test's ON80/ON50 copies are held by the planner. The index slip needs 15+ of our clicks. |
| 189 | Nov 5 | The rank cap is **3,000 searches a month**, and **4,000 for a search we convert on at 1.3 times the market or better**. Every source (SQP, DataDive, SoldScope) is read at its own number: the old 0.8 DataDive conversion is gone. This replaces the 2,400 in decisions 182 and 185. |
| 190 | Nov 5 | The skill folder is now `amazon-ppc-ai-bidding` (it was `...-2026-11-04`). A session that can't find the old name: `git pull`, then start a new session. Before and after: [whats-new-2026-11-05.md](whats-new-2026-11-05.md). |
| 191 | Nov 5 | **Sponsored Products and Sponsored Brands are priced in the same run.** Without the Sponsored Brands keywords (`need_sb_keywords.json`, also SB targets and themes) or the SP ad groups (`live_ad_groups`), `plan.py` stops with exit 2 and plans nothing; `--accept-unowned` no longer skips them. Read them and rerun. |

Decision 174 in one place, with the why: [docs/knowledge/apply-promote-2026-10-31.md](../knowledge/apply-promote-2026-10-31.md).

## Before the run

**"Should I do a readiness audit first?"** No (decision 172). `audit <ASIN> for the AI bidding skill` on a product
not yet AI-owned means onboard it (references/onboarding.md) and run the weekly run on it in the same session. Do the
read-only check (references/readiness-audit.md) only when the person explicitly asks for "read-only", "test" or
"shadow".

**"This product isn't in the AI program. Kim has to add it."** No. Any book owner adds it by asking (decision 172).
Create its product file (onboarding.md section 1), put the person's name in `registry.added_by`, and go on.

**A product file says `registry.stage` "queued"** (a lined-up product). Same thing: keep its fields, set the stage to
"onboarding" and onboard.

**Someone else is on the product.** `python scripts/dashboard.py team` shows claims. Also look at today's
#3d-ppc-standup. If a teammate has it claimed or posted about it today, tell the person and pick another. Kim has
also told the team to "leave them alone" on products he is fixing (gel pens, highlighters and the set, Oct 29): if the
product file's `open_items` or the standup says Kim holds it, don't run it.

**The local copy is old.** Always `git pull` first. The product files carry the invest log (the stop-loss clock), and a
stale copy restarts it. If the pull changed anything under `.claude/skills/`, say so and suggest a fresh session.

**`git pull` refuses or conflicts.** Never `git reset --hard`, `git stash drop`, `git checkout .` or `--force`: that
throws away someone's work. Most conflicts are in product files, because other teammates' runs commit to them too (Kim's daily
rank refresh did until it was retired on 2026-10-31).
- The person's own changes aren't committed: commit only their files (`git add <the product file> <the log>`, never
  `git add -A`), then `git pull --rebase`.
- A conflict in a product file the person didn't run: keep the version from main.
- A conflict in the product file they did run: keep main's newer rank and dashboard fields, and keep the run's own
  `invest_log`, `activity`, `open_items` and `brief` entries. Check the JSON loads (`python -m json.tool <file>`), then
  continue the rebase.
- Unsure: stop and show the person the conflict. Don't guess on the invest log.

**A connector is missing or signed out.** Stop and name it (AGENTS.md rule 5): "MarketplaceAdPros isn't connected in
this session. Connect it on claude.ai under Settings, Connectors, then start a new session." Connector tools
load when a session starts (Claude Code and Codex alike), so after reconnecting, a new session is needed. Never swap in another tool to get round it.

| Connector | Needed for | Without it |
|---|---|---|
| MarketplaceAdPros (with write access) | Every Amazon read and write | No run |
| Scale Insights MCP | SQP, search terms, keywords, costs | No run |
| A browser signed in to portal.scaleinsights.com (Claude in Chrome; Codex: browser-use, computer-use or Playwright) | Strategy assignment, blacklist, import rules, dayparting | The Scale Insights steps become a checklist the person clicks through (references/scale-insights-playbook.md). The MAP rows still go out |
| SoldScope | Bid estimate when Amazon gives no suggested bid; the season curve (Kim, Oct 30) | Seasonal products and searches with no Amazon suggestion can't be priced. Ask for it to be connected |
| DataDive | Rank Radar ranks (stop-loss, rank refresh) | Ranks are stale; the run still plans bids |
| Slack | The run's one message in #3d-ppc-standup | Give the person `notify.py`'s text to post themselves |

**Scale Insights calls start failing mid-session, though they worked earlier.** The session holds an old tool list.
Start a fresh session; nobody needs to reconnect anything (fixed it on Oct 26).

**The dashboard refuses: no token, 401 or "sign in".** The person signs in once on this laptop: in PowerShell (not
Claude), in the skill's folder, `python scripts/dashboard.py login`. They type their password there, never into the chat.
Don't run `dashboard.py secrets --personal`: that's the old way.

## While planning

**SQP is old (for example, Scale Insights' newest week ends Oct 17 on Oct 30).** Plan anyway. The run says how old it
was (`summary.sqp_age_days`). Scale Insights SQP always lags a week or more; don't wait for newer weeks (decision 172).

**Scale Insights says "MCP usage limit reached".** Don't wait for the reset. Scale Insights is the default; SoldScope and
MarketplaceAdPros are the backup (Kim, 2026-11-04): pull SQP from SoldScope and the keyword and search-term reports from
MarketplaceAdPros, and `scripts/report_sources.py` writes them in the planner's files (references/data-pull.md, "When
Scale Insights is out of allowance"). Never retype a file by hand. Say in the run log which source each input came from.

**A seasonal product (Christmas, Halloween, Valentine's).** Pull last season's SQP too (`last_season_sqp_*.json`,
references/data-pull.md) so this season's searches are priced on both seasons' clicks and purchases. If `plan.py` says
the product is in its "last mile", "off", "review" or "asleep" phase and plans nothing, that is correct: the phase's
steps are dated open items (`python scripts/season.py items`).

**"<ASIN> is in the launch stage (n SQP queries ... under 10)".** A real stop: a brand-new product has no SQP market
yet. Build its launch list (`scripts/launch_list.py`, onboarding.md "A product with no SQP yet"); the planner takes over
at 10 queries. Tell the person in one line.

**`plan.py` exits with code 2, or writes a `need_*.json` file.** It is asking for one more read, not failing. Fetch
what the file names, save it in the run folder and rerun `plan.py`:

| File | What to fetch (references/data-pull.md) |
|---|---|
| `need_suggested_bids.json` | Amazon suggested bids for the listed `searches` (MAP `get_amazon_ads_ad_group_bid_recs`, exact): the invest searches, the exact keywords at the suggested mid, and the searches over the rank cap that bid the suggested low (decisions 182 and 183). Its `keywords` list is empty since decision 183 (broad and phrase bid breakeven). Rate-limited: SoldScope's bids |
| `need_suggested_bids_business.json` | The same, read in the B2B ad group it names |
| `need_live_inventory.json` | Every live keyword and target (`live_keywords`, `live_targets`, `sd_targets`, `sd_campaigns`) |
| `need_settlement.json` | `settlement.json`: the last 14 days of settled orders (decision 169) |
| `need_sb_keywords.json` | The Sponsored Brands keywords (and targets and themes): every id group, every page. Required since decision 191: the planner won't plan without them, and `--accept-unowned` doesn't skip them. About 3,000 keywords on a big product; save each page as it comes |
| `need_visibility_data.json` | The visibility inputs (references/visibility.md) |
| `need_budget_recs.json` | Amazon budget recommendations |
| `need_listing_size_verification.json` | A fresh live listing read of the product's size (references/live-size-pauses.md) |

**Amazon's suggested bids time out or come back empty.** Retry once about 5 minutes later. Still nothing: save
SoldScope's estimate in `soldscope_bids.json`, write what you tried in `bid_sources_tried.json`, rerun. It never stops
the run (decision 106).

**"Save the dashboard decisions first".** Run the `dashboard.py reviews ... --save <run>/reviews.json` command the
message prints, then plan again.

**Unowned campaigns stop the run (coverage ledger).** Campaigns the ASIN's ads serve in that the planner can't match.
Shared ones (ads for other ASINs too) go into `ownership_scope` as excluded, untouched, and the run goes on (decisions
156 and 172): multi-ASIN campaigns are left out on purpose (product collections, cross-selling). Excluded shared
campaigns aren't unfinished work: don't list them as pending or ask about them again.

**Low ad spend, or a new product "isn't getting a boost".** Usually the bids are under what it takes to be seen. That's
what the run fixes (suggested bids, or SoldScope's estimate when Amazon gives none). It isn't a reason to skip or hold
the run.

**Big outputs.** MAP and Scale Insights pages can be 100+ KB. Save each response to a file in the run folder and read it
with Python. Pasting them into the conversation burns the person's Claude usage fast.

**The price changed recently.** It holds nothing (decision 168): the change is priced in at the new profit.

**Stock is low (14 days of cover or less).** Since 2026-10-31 (decision 174) the run parks its **increases** "For human"
(new rank campaigns, raises, new SB videos, budget and top-of-search increases, budget steps up). Cuts, pauses and holds
still go out, and the product gets one "Reorder stock" item. Don't hold anything else. The increases go out when a person
approves them on the dashboard, or when a person clears the product: add
`"stock_clearance": {"by": "<name>", "on": "<YYYY-MM-DD>", "why": "<reason>"}` to the product file (it lasts 7 days, or
until an `"until"` date) and plan again. Kim cleared B0SAMP0015 this way on 2026-10-31 because supply chain was on it.
Only a person decides a clearance: never add one yourself. A missing inventory cover file still stops the plan: pull it
again.

**"Prove first needs three orders."** Not since 2026-10-31 (decision 174): a search with **2 or more orders** at index
1.1 or better (decision 178; 1.25 that morning) gets its own Prove-first rank campaign, +30% top of search and its SB video. Its orders are the higher of
its SQP purchases and its search-term report ad orders (SQP already includes the ad-attributed purchases, so the two are
never added). Invest still needs 3 orders at 1.1, and a raise above breakeven 3 orders at 1.4.

**"This promotion is over the $2,000 guide" or "over the $60 loss line".** Information only (decisions 99, 100 and 174).
The run summary and the Slack message say so; nothing is parked, held or shrunk for money. The brakes are the stop-loss
per search (rank, impression share and organic orders), the 56-day re-promote cool-off, the weekly leak check (decision
175, glossary) and the low-stock park.

**"Under 50% organic, so the ordinary keywords bid 70%" or "the efficiency guard stepped bids down / held Prove first".**
Not since 2026-10-31 (decision 175). Ordinary keywords bid 100% of breakeven whatever the organic share; 75% only on a
search we already rank top 10 for; Trim (index under 0.8) stays at 70% of its own breakeven. The efficiency guard is now
the weekly leak check: it only pauses ordinary keywords with 15+ clicks and no orders when the ordinary campaigns lost more
than $10 in 7 settled days. It never holds a Prove-first launch.

**"Why is this Hold (or Test, or Discovery) keyword bid above its breakeven?"** The suggested mid (decision 177, rulebook
2i): a validated keyword (2+ orders, about the market's conversion) or one still in its launch test bids Amazon's suggested
middle bid so it stays visible, above or below breakeven. That is expected, not drift, and the raise is Auto. Its why says
where the mid came from (Amazon, SoldScope or an estimate); `summary.mid_bid` lists them all with their 90-day spend. A
launch test ends at 2 expected orders at the product's ad conversion with no order (15 to 60 clicks: 20 at 10%, 40 at 5%;
back to its normal price, and the leak check may pause it), or 3 expected orders with one (at most 90 clicks). While in the
test the leak check leaves it alone (decision 178).

**"Rulebook 2h says ordinary campaigns use 0% top of search, so a placement reshape with a top-of-search modifier needs
Kim."** No. The placement shape (decision 140, rulebook 2e) lowers the base bid and raises the better-converting placement
back, so an ordinary campaign can end with, say, +28% top of search while no placement bids more than its price. It is the
planner's own Auto row; apply it (clarified 2026-10-31 after Codex asked on the 50-pack; the code has worked this way since decision 140).

**"Non-rank bids are 85% of breakeven."** Not any more. That was decision 139 (Oct 26); decision 157 (Oct 28) put them
back to 100% (`thresholds.non_rank_bid_factor` 1.0) because spend on the cheap products fell too far. The run prices
non-rank keywords and targets at their full breakeven click.

**A referral fee that halves the profit** (for example $2.37 to $1.19 on the first settled read). That was a bug in
`scripts/referral.py`, fixed 2026-10-31: Scale Insights' ReferralPercent 0.15 means 15%, and the reader took it as 0.15%.
If an older product file was hand-corrected for it (a note in `referral_override`), leave it.

## While applying

**When to apply.** Apply as soon as the run finishes, at any hour and any day. The only exception is the switch hold: no
writes in the 2 hours before a Scale Insights rule 203 ON switch, and none in the hour after it. `scripts/write_window.py
check` enforces this. On hold, wait until its `safe_from` time, or park the folder, then apply (decision 174). Don't wait
for office hours or 10:00 SGT. The ON switches are 21:00 SGT on weekdays and 20:00 SGT on Saturday (an hour later each
once US clocks go back on Nov 1).

**Live bids don't match the plan: $1.28 now, $1.60 planned (or the reverse).** That's the weekend dayparting cut
(Saturday 20:00 to Monday 21:00 SGT, bids × 0.8 since 2026-10-31; × 0.6 at the −40% from Oct 26 to Oct 31), not drift
(decisions 150 to 152 and 174). `write_window.py prewrite` says `replan`: plan again from a fresh read and go on. Only
`stop` is a real change to report. The code reads the cut from the bids themselves, so a week-old plan made under × 0.6
is recognised too.

**A read-back "mismatch" on many rows at once.** Suspect the file before the bids. Save the read-back as MAP
`list_resources` rows (a plain list, or `{"data": [...]}`, `{"items": [...]}`, `{"results": [...]}` or MAP's text wrapper)
and dry-run `autonomy.py readback` first. Since decision 163 it stops with an input error, writing nothing, when half or
more of the rows are missing from the file: read again, don't report a mismatch. Before that fix a wrong shape compared
every row against nothing (B0SAMP0006, Oct 25: "45 of 45 not as written", all actually fine). A real mismatch on a few
rows: send those rows again through MAP, read them back, and record only what reads back (`applied --rows`).

**A guard tripped (Day-1 spend over 1.5×, a real read-back mismatch).** It opens an alert for the book owner. Auto stays
on (decision 163). Say what tripped in the Slack message; don't switch anything off.

**The product's Auto is off.** Someone switched it off by hand. Plan it as a shadow (preview only: write the preview,
publish `--state proposed`), and tell the person only Kim turns Auto back on. Don't change `auto.enabled` yourself.

**Old campaigns spending (TOS 900%, SB video launches, AMC "Low Bids").** Since decision 155 the planner covers them:
top-of-search goes to 0% outside rank searches and paused or shared ones are cut-only. If spend still jumps the day
after, check those campaigns before blaming the new bids (Oct 26 spike: docs/knowledge/full-coverage-2026-10-27.md).

**A teammate changed bids by hand in Scale Insights (for example a manual bid import).** The morning check
(`scripts/si_changes.py` on `get_change_history`) lists the products to run today. The next run puts the AI's prices
back. Don't revert anything by hand.

## After the run

- `dashboard.py applied` straight after the read-back, then `log_invest.py`, the run log in `logs/`, `dashboard.py publish
  --state applied`, `notify.py` and its text posted in #3d-ppc-standup (C0EXAMPLE01).
- **Commit and push only this run's files:** the product file and the run log (and anything `approvals`, `applied` or
  `autonomy.py` wrote). Never `runs/`, secrets or `.env`. `git pull --rebase` before pushing. Use the person's own git
  identity.
- **A dashboard publish refused with 409:** someone published after your copy. `git pull`, publish again. Never `--force`.
- If you learned something durable that isn't here, add it to this page or a note in `docs/knowledge/` and push it.
  You have no memory between sessions; the repo is the memory.

## Claude Code and Codex differences

Same skill, same files, same rules. Only the tools and the way the skill is found differ.

| | Claude Code (Alex, Sam, Lee) | Codex (Kim) |
|---|---|---|
| Reads at session start | `CLAUDE.md`, which imports `AGENTS.md` | `AGENTS.md` |
| Finds the skill | `.claude/skills/amazon-ppc-ai-bidding/` | The pointer in `.agents/skills/amazon-ppc-ai-bidding/`, which leads to the same folder. Also read [docs/codex-operations.md](../codex-operations.md) before the first connector or browser step |
| Asks the skill to run | `run the AI bidding audit for <ASIN>` | The same words, or `$amazon-ppc-ai-bidding run <ASIN>` |
| Scale Insights web app | Claude in Chrome, in the person's own Chrome, signed in by them | browser-use or computer-use on a signed-in Chrome or Edge, or Playwright with a saved profile (codex-operations.md "Browser"). It made Scale Insights changes on Oct 26–27 |
| Connector tool names | Long prefixes (`mcp__<id>__get_sales_data`): find tools by function name | The server's own names (`scale_insights.get_sales_data`) |
| Permission prompts | The person clicks Allow. A tapped card or a relayed message isn't the person's typed yes | `approval_policy=never` means no prompts. It doesn't mean writes are forbidden, and it doesn't add permission. A real denial still stops that action |
| "Artifact" preview (shadow runs only) | Publish with the Artifact tool | Write `runs/<ASIN>-<date>/preview.html` and give the path, plus `dashboard.py publish --state proposed` |
| Subagents | Allowed for parallel reads | Run the steps one after another |
| Large outputs | Claude Code saves them to tool-results files: process those with Python | Save each raw response yourself; the scripts read MCP envelopes (codex-operations.md "Readback") |
| Memory between sessions | None for teammates: the repo is the memory | None: the repo is the memory |

If both agents work in the same folder at once (Kim's laptop), each stages only its own product file and log, and
never stashes or resets the other's work.

## When a run stops part way

**The session crashed, ran out of usage, or the person closed it mid-apply.** Don't apply the folder again from the top.
1. Read back what is live now (MAP `list_resources` for the folder's rows) and compare with the folder's `rows.json`.
2. Record exactly the rows that went out: `dashboard.py applied ... --folder auto --rows "<row_id>,<row_id>"`.
3. The rest waits for the next plan, in a new run folder (`runs/<ASIN>-<date>b/`, for example). A folder that partly went
   out is never applied again; its `--dry-run` check refuses it, and that refusal is correct.
4. Then finish the record as normal: log, publish, Slack, commit and push.
Never `approvals --discard-unapplied` a folder that partly went out before recording what went out.

**A Sponsored Brands video build stopped part way** (the campaign was made, a keyword failed). Record what went out with
`--rows`. `applied` lists the missing keywords under `add_by_hand`: add them to the campaign that now exists (MAP
`sb_keywords` create), read them back, and never apply the build again.

**MAP is down or rate-limits a read that won't clear.** Wait about 5 minutes and retry once. Still failing on the live
inventory: plan with `--partial-inventory "<why>"` and say so in the log. Failing on a write: stop the writes, record what
went out, report the rest.

## Particular kinds of product

**Christmas cards and other seasonal products.** Since Oct 30 the 13 Christmas harvest cards onboard now, in harvest mode
(docs/christmas-2026-onboarding.md, decision 171): Alex 5, Sam 5, Lee 3. Plan on whatever SQP exists plus last
season's (decision 172); the season block in the product file decides the phase. Kim, Oct 30: "the skill should take the
season's curve into account", which needs SoldScope connected. A card with a thin margin (B0SAMP0021 at 18%) will bid low
and get little volume: that's correct at its margin. Only a price change helps, and price is Kim's.
Other Christmas cards not yet on AI bidding (docs/sweep-tiers.csv; most were onboarded Nov 2 to 3) can be added by their
book owner the same way (decision 172); Lee assigns which owner takes which.

**A brand-new launch with under 10 SQP queries.** See "launch stage" above. The planner can't price it yet: the launch
list and the team's hand-built launch structure carry it.

**Products whose campaigns are shared with other ASINs** (cross-selling, product collections, B2B). The AI owns only
the campaigns whose every ad is this ASIN. The rest are listed in `ownership_scope` as excluded and stay with Scale
Insights. Never touch their bids, budgets, placements, negatives or states.

**Products in the overnight test** (B0SAMP0018, B0SAMP0022, B0SAMP0017, B0SAMP0023, B0SAMP0005, B0SAMP0024 in round 2,
from 2026-11-04). Their copy campaigns are named `ON80 | ...` (renamed `ON50 | ...` in round 2) and run on Scale Insights
rule 21248. The planner holds every row on a copy in `held/` (`experiment_hold` on the row): the test's own thread sets
those bids. Run and apply the product as usual; its original campaigns are AI-bid like any other. Never apply a held row by
hand.

**Brand searches ("yourbrand ...").** Organic only (guard #27): the run doesn't bid on them. That's on purpose.

**A product with no Sponsored Brands video asset.** The SB video rows can't be written. They park "For human" for the
book owner to supply a video. Everything else goes out.

## For Growth (listing hand-over)

When a run finds proven searches missing from the live listing copy, it raises a For Growth item (decisions 124, 166, 167).
The run itself posts the For Growth line in #3-marketing-traffic and moves or creates the product's item on Monday board
9000000011 in "[GROWTH TEAM] - For Listing Optimisation" with status "Optimise Listing". No approval needed. The run never
edits the listing; the Growth team does (`growth-listing-optimizer`). At most one new item per product every 14 days.

## Running several products in a day

- One product per run (AGENTS.md rule 3). Finish one completely (through the push) before starting the next. In one
  session is fine; a fresh session every 2 or 3 products keeps the context small and saves usage.
- `run the morning routine` works out which products are due (`scripts/routine.py`) and runs them one after another.
- Before each product: `git pull` (a teammate may have committed to it) and claim it.
- Many products in parallel on one machine (Kim's sweep box): [runbooks/](../runbooks/README.md).

## Saving the person's Claude usage

The team's Claude plans have limits, and a full run is large.
- Save every big MCP response to a file in the run folder and read it with Python; never paste raw pages.
- Don't re-read the whole skill every product: SKILL.md once, then the reference a step points to.
- Don't re-pull data already in this run folder unless the plan asks for it.
- Opus on High effort for a normal run; Sonnet on Medium for a status check or a rank refresh. Extra High only for an
  unusually messy onboarding.

## On a Windows laptop

- The repo may sit in OneDrive under a path with spaces: quote every path.
- `python` or `py`, whichever runs Python 3. The scripts need only the standard library.
- Use raw strings for Windows paths inside Python (`r"C:\Users\..."`): `"\202..."` turns into an escape character.
- `rm -rf` is usually blocked: move unwanted files aside instead. `runs/` is gitignored anyway; never delete it mid-week,
  because the next run settles the last one from it.
- Each teammate commits with their own name and email. If git asks for an identity, set it for this repo with
  `git config user.name "<name>"` and `git config user.email "<email>"`, using the person's own.

## How to know the run is really finished

All of these, in this order. If any is missing, the run isn't done: say which.
1. Last week's run settled (Day-1 check, approved rows applied).
2. The `auto/` rows applied and every row read back (or the mismatches named).
3. `dashboard.py applied` recorded them, and `log_invest.py` ran.
4. The run log is in `logs/<date>-<product>-weekly-run.md` and `dashboard.py logs --push` ran.
5. `dashboard.py publish --state applied` and `refresh` ran; the product's page shows today's run.
6. `notify.py`'s text is posted once in #3d-ppc-standup.
7. The product file and the log are committed and pushed to main, and `git status` shows nothing of this run left over.
8. The claim on the dashboard is released.

## Words the skill uses

| Word | Meaning |
|---|---|
| Book owner | The teammate who owns a product's bids (Alex, Sam, Lee). The product file's `registry` says who |
| AI-owned / Scale Insights-owned | Who sets the product's bids. Never both |
| Auto lane | Rows the run applies by itself. **For human**: rows that wait for a person on the dashboard. **Monitor**: held, judged again next run |
| SQP | Search Query Performance: Amazon's weekly per-search report of impressions, clicks and purchases, ours and the market's |
| Index (IDX) | Our conversion on a search ÷ the market's. 1.1 or more is a rank search worth investing in; under 0.8 is trimmed |
| Invest / Prove first / Hold / Defend / Test / Trim | The role each search gets from its evidence (rulebook section 1) |
| Breakeven | The bid at which ad profit is zero, from the product's profit per unit and the search's conversion |
| Harvest | The auto/broad ad group that finds new searches; proven ones are promoted to their own exact keyword (an SKC) |
| SKC | Single-keyword campaign: one exact keyword in its own campaign |
| Stop-loss | The check at months 3, 6, 9 and 12 of a rank investment: if organic rank and sales didn't improve, step it down |
| Day-1 check | 24 hours after an apply: did spend jump more than 1.5×? |
| Read-back | Reading every written row back from Amazon to check it is what was sent |
| Leak check | The weekly check on the ordinary keywords (decision 175): if the product's ordinary campaigns, Sponsored Products and Sponsored Brands (not rank, not B2B), lost more than $10 over the last 7 settled days, the run pauses ordinary keywords with 15+ clicks and no order in 90 days. No bid cut, no hold on new campaigns. Before Oct 31 it was the "efficiency guard" |
| Top-10 rule | An ordinary keyword on a search we already rank top 10 for without ads bids 75% of breakeven (75% of the suggested mid when it bids the mid). Rank searches keep investing |
| Suggested mid | Amazon's suggested middle bid for a keyword (decision 177): validated and launch-test ordinary keywords bid it instead of breakeven. When Amazon is rate-limited or has none, SoldScope's middle cost per click; with neither, an estimate |
| Launch test | A Test or Discovery keyword with 0 or 1 orders bids the mid until 2 expected orders at the product's ad conversion (15 to 60 clicks; 20 at 10%, 40 at 5%), or 3 with one order (at most 90). The leak check doesn't pause it meanwhile. 2 orders validates it (decision 178) |
| Organic-share brake (gone) | Until Oct 31: a product under 50% organic bid its ordinary keywords at 70%. Dropped by decision 175; the share is only reported now |
| 203 / dayparting | Scale Insights' Optimum Hours schedule: ads off in the US night, bids × 0.8 at weekends (−20% since 2026-10-31; −40% from Oct 26) |
| 202 Brake | The one Scale Insights bid rule allowed on AI products: −30% on 26+ clicks and no orders, reduce-only |
| `ownership_scope` | The product file's list of shared campaigns the AI must not touch |
| Run folder | `runs/<ASIN>-<date>/`: the raw pulls, the plan and the payloads. Gitignored, stays on the laptop |
| Product file | `.claude/skills/amazon-ppc-ai-bidding/data/asins/<ASIN>.json`: the product's state, invest log and history. Committed |

## What still needs a person

Park these "For human" (the skill does this) and don't do them yourself:

| Who | What |
|---|---|
| Kim | A price change; taking a product off AI bidding; turning a product's Auto back on; the rulebook and `config.json`; dayparting beyond the standard 203 setup |
| Any person (usually the book owner) | Clearing a low-stock product so its increases go out (`stock_clearance`, decision 174), or approving its parked increases on the dashboard |
| Lee | Revamping images, cutting or stopping a product, improving a listing or offer |
| The book owner | Any bid call on their own products the run parks for a person (a one-word or unlisted search's promotion, a row that can't be written) |

Never: Scale Insights bid rules or "Automate assignment" on an AI product (the 202 Brake is the one exception), the SKC
audit on an AI product, hand edits to bids in Seller Central, typing a password, the Weave canvases (app.weavy.ai).
