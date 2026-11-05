---
name: amazon-ppc-ai-bidding
description: >-
  YourBrand's AI-managed Amazon PPC workflow, one ASIN per run: onboarding from Scale Insights (straight to
  the run, no readiness audit first), weekly keyword and product-target bidding, rank investment, Sponsored Brands video, harvest,
  negatives and stop-loss checks. Use for onboarding an ASIN, a weekly PPC run, rebidding, investing for
  rank or diagnosing delivery on an AI-owned product. The deterministic planner uses SQP conversion,
  Amazon suggestions and economics; verified dayparting pauses do not stop base-bid optimization.
  Authorized Auto rows apply through MarketplaceAdPros and the signed-in SI browser, with readbacks,
  dashboard records and one Slack recap. Preserve shared-campaign exclusions and independent serving
  guards. Products still owned by SI use the SKC and negative-audit skills instead. Before running, read
  references/field-guide.md in the repo root: it carries newer decisions than parts of this file.
---

# PPC AI bidding audit (YourBrand), last updated 31 Oct 2026

> **Public copy.** This is a cleaned copy of a skill that runs a real seller's account. Product files, the team
> dashboard server and every account ID were removed. Names (Kim = the owner, Lee = the team lead, Alex and Sam =
> teammates) and ASINs (`B0SAMP…`) are placeholders, and `YourBrand` stands for the brand. Paths under `docs/`,
> `logs/` and the dashboard point to the original private repo and are not included. Before a first run, put your
> own MarketplaceAdPros IDs and Scale Insights strategy and rule IDs in `config.json`; products get their files in
> `data/asins/` when they are onboarded.

**Running this on your own laptop?** Read [references/field-guide.md](references/field-guide.md)
first (in this skill's folder): the situations teammates' sessions hit, what to do about each, and the
standing calls Kim has made that this file's older paragraphs may not show yet. Where the two differ, the newer
decision in docs/decisions.md wins.

**Running several products at once, a price change, or the Scale Insights switch?** The runbooks in
[docs/runbooks/](../../../docs/runbooks/README.md) cover preflight, connector sign-in, the write lock, the switch order
(objectives first, bids, hours last) and resuming without duplicate writes. They add no bid policy.

Scale Insights' stacked target-ACOS and inch-up rules set bids from one lagging number and pinned
low-priced products below the price of being seen. This workflow replaces them for AI-managed products:
every search gets a role from its evidence, with same-query IDX where available. Economic bid estimates,
contextual Amazon suggestions and actual delivery are separate inputs. Missing market data means IDX unknown,
not a failed keyword. Since 2026-10-22 (decision 98) the run applies its own Auto rows and parks only the
decisions it can't make "For human"; nothing else goes live without a person's yes.
Piloted on the 100-pack Christian bookmarks (B0SAMP0001, B0SAMP0002), launched 2026-10-17.
The team follows every AI-managed product on the dashboard, one page per ASIN:
https://your-dashboard.example.com (references/dashboard.md). Operational runs publish to it;
the read-only readiness audit (a product not yet AI-owned) never publishes, applies rows or enters a product in the
live registry.

## Recommended model and effort

Defaults requested by Kim on 2026-10-24 (SGT):

| Work | Codex | Claude |
|---|---|---|
| Regular full audit and autonomous implementation | **GPT-6.1 Sol, High** | **Claude Opus 5.5, High** |
| Simple rank refresh, read-only reporting or status check | GPT-6.1 Sol, Medium | Claude Sonnet 5.5, Medium |
| Complex onboarding, contradictory evidence or difficult serving repairs | GPT-6 Astra, High | Claude Opus 5.5, Extra High |

The Python planner calculates bids; the model reconciles Amazon/SI evidence, ownership, dayparting and exceptions,
then executes and verifies the authorized changes. For unusually difficult rule redesign, Codex may use GPT-6 Astra
with Extra High effort. Extra High and Max are not routine defaults. These are workload-based recommendations,
not benchmarks on this account. Honor an explicit user model choice; this guidance does not change the active
session's settings or make a different model a blocker to running the skill.

Model guidance checked on 2026-10-24: [OpenAI](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[Anthropic](https://platform.claude.com/docs/en/models/overview). Recheck availability when revising these defaults.

## The rules that override everything

**Execution timing (Kim, 2026-10-24, decision 114):** an authorized operational audit applies its eligible
changes during that audit, on any day. Never defer because it is a US weekend, overnight, or an older plan says
Monday in `apply_after`. Verify dayparting bid modifiers and readbacks per weekly-run.md; preserve the actual
schedule, shared scope and genuine eligibility controls.
**Re-audits are operational runs (Kim, 2026-10-24, decision 116):** an audit or re-audit of an AI-owned product
whose Auto lane is on (after a price change, for example) applies its eligible Auto rows like any run. Only these stay
read-only: the readiness audit of a product not yet AI-owned, an Auto-off product, and a preview, test or shadow run a
person explicitly asks for. A failed preflight (git pull, dashboard, connector) stops the writes: report a blocked
autonomous run with its blockers, never a completed read-only re-audit, and never switch to a shadow copy instead.

1. **One owner per product's bids.** A product is either AI-managed (this skill) or on Scale Insights bid
   rules, never both: SI rules run every evening (about 18:10 UTC) and overwrite AI bids within a day.
   Check the registry first (references/team.md). Never attach an SI strategy with bid rules to an
   AI-managed product, and never run SI's "Automate assignment" on one (it reassigns every ad group).
   One named exception (Kim, 2026-10-17): the reduce-only bid rule **202 Brake** (26+ clicks and no orders in
   30 days → −30%, floor $0.10, once a week) inside strategies 101, 111 and 121. It never raises a bid and never
   touches exact keyword owners (103), harvest (104) or audience groups.
   **Bounded shared-campaign exception (Kim, decision 109 on 2026-10-23, and decision 111 adding B0SAMP0003 on
   2026-10-24):** the products with an approved `ownership_scope.mode = exclusive_campaigns` use AI only on exclusive
   campaigns. The exact shared campaign
   IDs in that scope and every descendant remain solely SI-managed. Never change their rules, bids, budgets,
   placements, states, negatives or shared product-list behavior. The planner and apply preflight enforce the
   exclusions, including against older plans. Verify live creative membership before writes; a newly discovered
   shared campaign is added to `ownership_scope` as excluded by the run that finds it, which then goes on (decision 172,
   2026-10-30: no one's approval is needed, for any product). See docs/knowledge/si-mixed-asin-ownership-2026-10-23.md in the repository.
   **Completion reporting (Kim, 2026-10-24):** approved shared-campaign exclusions are outside the authorized
   work, not unfinished onboarding. Leaving them untouched fulfills the scope boundary. Never count them as
   pending, held, blocked or "For human", ask again to migrate them, or call a run incomplete solely because they
   remain SI-managed. Keep their IDs and ownership evidence in the record; mention the exclusion once when useful.
   Assess completion against the authorized exclusive campaigns and their required checks. Still report genuine
   exclusive-group SI synchronization, protection, serving, readback and Day-1 follow-ups separately. Unknown
   membership, an unapproved scope or a newly discovered mixed campaign remains a real ownership gate.
2. **Autonomous runs: the Auto rows apply without a per-run OK; everything else waits for a person's yes**
   (Kim, 2026-10-22, decision 98: "build autonomous runs as in the design with the defaults: notify in Slack
   #3d-ppc tagging the person, the AI applies stop-loss step-downs itself and notes them, and turn it on for all AI
   products"; the recap goes to #3d-ppc-standup, C0EXAMPLE01, since the same evening). Auto is on for every AI
   product (config.json `auto.enabled`; a product file's `false` is its kill switch). The run applies its Auto rows during the audit on any day through MarketplaceAdPros and, for the standard Scale Insights setup, the signed-in browser; reads back
   every row; publishes the result as applied; and posts one Slack message (`scripts/notify.py`). Bid and rank calls are
   the AI's (Kim, 2026-10-23, decision 107: "the bid changes and rank investments are all actually programmatically
   calculated and quantifiably decided"). Rows parked "For human" (rulebook 7.9: a price, a person's earlier decision, a
   one-word or unlisted search's promotion, a Scale Insights rule set beyond the standard setup, a row that can't be
   written, a guard that tripped) are never applied without a person's yes on the dashboard. People run
   launches (AMC and B2B campaigns) and prices. Any book owner adds a product to the program (decision 172). Money is a guide, not a
   gate (Kim, 2026-10-22, decisions 99 and 100): $2,000 a month a product (`auto.invest_guide_month`), the product's
   investment band and the $60 loss line for one search are named in the summary and the Slack recap when a plan is
   past them, and nothing is parked for them. A search the stop-loss stepped down is held
   from re-investment for 8 weeks (`auto.repromote_cooloff_days`). Re-check live before writing (references/live-checks.md); a live state that changed an action is
   applied only in the plan's direction and reported. A listing or price change is never written by a run.
3. **One ASIN per run.** Loop the catalog one product at a time; never batch products into one plan.
4. **House rules.** Date every figure. Record the reasoning, not just the action. Never commit credentials.
   Negatives go through the `amazon-negative-keyword-audit` skill's approval table.

## Modes

**Standard onboarding hours (Kim, 2026-10-24):** every newly AI-managed product's AI-controlled ad groups
must use Scale Insights **203 Optimum Hours, weekends on with bids -20% (21246)** (the weekend cut was −15% at first,
−40% from 2026-10-26, −20% since 2026-10-31, decision 174). This is part of the
authorized standard handoff, not a separate dayparting approval. Replace legacy direct product schedules on
verified exclusive groups; a strategy saying Optimum Hours is insufficient when a direct override survives.
Preserve shared-campaign exclusions and an explicitly approved experiment or custom schedule. Verify effective
rule IDs for SP, SB and SD, including low-bid/audience groups and newly synchronized harvest/rank groups,
before declaring onboarding complete. See onboarding.md section 7 and scale-insights-playbook.md.
**No AI product stays on Scale Insights rules (Kim, 2026-11-04, decision 180):** onboarding moves every one of its
exclusive ad groups off the legacy strategies and rules onto the AI objectives (101 to 144 in config.json
`scale_insights`; exact owners on 103/144 with the blacklist unassigned), and its legacy schedules give way to 21246 once
its AI bids are written and read back, before Scale Insights' ~02:10 SGT nightly run (decision 135). Shared campaigns keep
their setup.

| Mode | When | Guide |
|---|---|---|
| Onboard | "Audit <ASIN> for the AI bidding skill" (or "onboard", "add to AI bidding") on a product not yet AI-owned: any book owner may ask, no one else's approval (decision 172). Onboard it, then run the weekly run on it straight away, keyword by keyword | references/onboarding.md |
| Read-only check (optional) | Only when a person explicitly asks for a read-only, test or shadow check of a product not yet AI-owned; never a step before onboarding (decision 172) | references/readiness-audit.md |
| Weekly run | Every AI-managed product, once a week (rebid, harvest review, negatives, stop-loss), and any "audit" or "re-audit" of an AI-managed product with Auto on: it applies its eligible Auto rows (decision 116) | references/weekly-run.md |
| Day-1 check | 24 hours after any apply, and at the start of the next run (`scripts/autonomy.py day1`: a spend trip opens an alert, Auto stays on, decision 163) | references/weekly-run.md, "Day-1 check" |
| Budget check, catalog | Monthly machine check: every campaign NOT AI-managed (`budget_headroom.py catalog`) | references/budget-headroom.md |
| Data stage | Every plan: the product is launch, early or mature | A product's data stage decides what may be promoted: rulebook section 10 (references/rulebook.md) |

The read-only check's guide (only when explicitly asked) overrides the operational apply, publish, claim and notification steps below. Its
read-only connectors and isolated files are sufficient; MAP write access and a browser are not needed for that mode.

## Lanes: who says yes

**Inventory policy (Kim, 2026-10-31, decision 174; replaces the 2026-10-24 policy):** at 14 days of stock cover or less the run parks its increases (promotions, raises, new SB videos, budget and top-of-search increases, budget steps up) For human until a person approves them or clears the product (`stock_clearance` in its file, 7 days by default; never added by an agent). Cuts, pauses and holds still go out, and Auto stays on. From 2026-10-24 to 2026-10-31 low stock held nothing. Keep the dated inventory alert; missing or unreadable inventory inputs, verified out-of-stock/buyability blockers, and all other independent guards retain their existing behavior.

**Confirmed wrong-size pauses (Kim, 2026-10-24):** verify actual product dimensions in a fresh live listing,
save raw evidence and `listing_size_verification.json`, then let eligible positive-keyword relevance pauses
apply through Auto. Fingerprints alone, ambiguous sizes and routing/replacement pauses retain their holds;
all other guards remain. Resolve `need_listing_size_verification.json` during the run, without another size
approval. Read [live-size-pauses.md](references/live-size-pauses.md) when such rows appear.

Every change in a plan has a lane (references/rulebook.md, section 7): **Auto** (the run applies it), **For human** (the
dashboard's "Needs human": parked, with its row on the run's Bids item and a line in the Slack message tagging who decides)
or **Monitor** (held, re-judged next run). Since 2026-10-22 (decision 98) Auto is on for every AI product, and since
2026-10-23 (decision 107; stock policy updated 2026-10-31, decision 174) the human list is only: a price; an increase on a product with 14 days of stock or less (until a person clears it); a row a person's decision holds; a one-word or unlisted search's promotion; a Scale Insights rule set beyond the standard setup; a row that can't be written (no video asset, no B2B campaign); a guard that tripped. The AI decides the rest itself: a close call
short of the ladder is its "not yet" (Monitor, whatever its size); a big bid cut goes straight to its price (no 50% step since
decision 168); a non-standard budget or boost is written at the standard (a product file's budget_overrides is the
standard for its search); a search-term-fallback promotion goes out as a Prove-first test; a raise past a product's own raise count (none since decision 164), a
stop-loss with no keyword to step down yet and a row with no bid are held for the next run; a visibility check that
couldn't be answered holds nothing (only a "no" does). The Hold uplift test (decision 108, +15% at index 1.0-1.1) ended on
2026-10-25 (decision 135): Hold bids breakeven (the suggested mid with 2+ orders since decision 177; a raise to the mid is Auto). A Prove-first promotion needs 2 orders at index 1.1 since 2026-10-31 (decisions 174 and 178)
(decision 174; 3 from decision 135), counted as the higher of SQP purchases and ad orders; Invest needs 3 at 1.1. A search
SQP has seen in fewer than 14 days waits at every stage (decision 135). Everything else that can be written is Auto: cuts (Invest and invested
searches too), pauses with orders, Sponsored Brands rows, funnel negatives, harvest bids, budget steps, the standard Scale
Insights setup, onboarding and season-switch rows, and the stop-loss step-downs (`scripts/stop_loss.py`). A missing inventory cover
file stops the plan up front with what to pull again (decision 168). SQP of any age is planned on: the run uses the newest
Scale Insights has and says how old it was, and a seasonal product adds last season's SQP (decision 172). A recent price change
holds nothing, a big cut goes straight to its price, and a keyword with no clicks is priced like any other (decision 168). Low stock (14 days of cover or less) parks the increases For human and adds one manual inventory item; cuts, pauses and holds still go out, and a person's `stock_clearance` in the product file lets the increases out (decision 174; from 2026-10-24 to 2026-10-31 it held nothing). No row is parked for money (decisions 99, 100 and 174): the
summary carries the product's planned invest against the $2,000 guide, the promotions past the product's investment band and
those past the $60 loss line for one search, and the recap names them. A row that re-invests in
a search stepped down at stop-loss in the last 8 weeks is held (Monitor). `plan.py` splits the payloads into `payloads/auto/`
(with `scale_insights_steps.json`, the browser checklist), `review/` and `held/` (`approved/` is built later); the manifest
says `approval_required` false for `auto/`, true for `review/`. references/weekly-run.md says which folder may be applied,
and when: during the audit on any day, checked first with `dashboard.py applied ... --dry-run` (it refuses `auto/` on a product
whose Auto is off), read back row by row, then recorded with `applied`. The guards are `scripts/autonomy.py` (`day1`,
`readback`, `switch-off`, `program`, `stock`); the Slack message is `scripts/notify.py`. The morning routine's work list is `scripts/routine.py`;
the Hold uplift test's baseline and review are `scripts/hold_uplift.py` (the test ended on 2026-10-25, decision 135:
`hold_uplift.enabled` is false, so no run records a new baseline). `dashboard.py reviews` saves the
team's decisions before planning; `approvals` turns their Approve clicks on the Bids card into `approved/`.

## Tools a teammate needs

- **MarketplaceAdPros** with write access ("View and make changes"): campaigns, keywords, negatives, bid recs, listings, report SQL.
- **Scale Insights MCP** (read): SQP, search-term and keyword reports, product costs, campaign settings.
- **Scale Insights web app in Chrome** (Claude in Chrome): strategy assignment, blacklist/whitelist, import rules. SI has no API for these.
- **DataDive MCP**: Rank Radar ranks for the stop-loss. Creating a radar within the quota needs no approval
  (decision 105; references/onboarding.md, section 5).
- **SoldScope MCP**: the estimated bid for a search Amazon gives no suggestion for (decision 106; data-pull.md).
- **SP-API tools** (`amazon_get_competitive_pricing`): live price check.
- Python 3 for the scripts (Node optional, for the preview self-check).
- To publish to the dashboard: the publish token in `~/.config/your-ppc-repo-dashboard/secrets.env`. To change
  the dashboard's server: the Railway MCP (references/dashboard.md).

Without Chrome, the SI steps become a manual checklist for the teammate (references/scale-insights-playbook.md).

## Morning routine (decision 107)

Kim, 2026-10-23: "so that in the long term, I can program this as a routine that runs every day or every morning at a
certain time". A person starts it ("run the morning routine"). The skill never creates a scheduled task, cron or routine,
and never asks or reminds anyone to set one up (Kim, 2026-10-23: "I don't want it to create or prompt the humans for a
routine"). When started, it works through the morning on its own:
1. `git pull`, then `python scripts/routine.py` (it changes nothing). It lists, in order:
   - `runs`: the AI products whose weekly run is due today (the later of the registry's next_run and the last run + 7
     days; a product that already ran today is never listed);
   - `checks`: each product's own due items (Day-1 checks and re-checks), `with_run` when its run settles them;
   - `reviews`: dated reviews that are due, the Hold uplift test's among them;
   - `waiting_on_people`: a count only. Nothing in the routine asks a person anything.
   Then the hand-change check (decision 155): Scale Insights `get_change_history` (source manual, raw, days 2, every page
   saved to files), `python scripts/si_changes.py <pages>`. Each product in its `run_today` is run today (added to `runs`
   if it wasn't due), and its `message` goes in the routine's Slack line.
2. For each product in `runs`: claim it (`dashboard.py claim`; skip one someone else holds), then the weekly run below,
   end to end: settle, pull, plan, apply the Auto rows (any day; no calendar deferral), read back,
   record, publish, Slack recap. (While the Hold uplift test ran, Oct 23 to 25, the first applied run with Hold uplift
   keywords recorded its baseline with `python scripts/hold_uplift.py baseline --run <run>`; the test ended, decision 135.)
3. For each product in `checks` without a run today: do the check (references/weekly-run.md, step 2 for a Day-1 check;
   step 12.1 for "Apply held ... rows", step 12.5 for "Re-check ... bids") and close the item in the product file.
4. For each due review: run it. `routine.py` skips the review of an ended experiment (counted in `ended_reviews`), so the
   Hold uplift test's (ended 2026-10-25, decision 135) is no longer listed. While it ran, its review was: pull SI
   get_keyword_performance with days=28, run `hold_uplift.py review --asin <ASIN> --kw <pages>`, and once every product
   is reviewed `hold_uplift.py verdict`; then follow docs/experiments/hold-uplift-2026-10-23/protocol.md (keep, or set
   config.json `hold_uplift.enabled` false) and mark the review `done` with the date.
5. Commit and push what changed, `dashboard.py logs --push` the day's logs, and end with one line in #3d-ppc-standup only
   when something was parked For human.

## Weekly run in one screen

The full runbook, with every check and refusal, is references/weekly-run.md; this is its outline.

1. **Settle last week first** (weekly-run.md steps 1-2). Confirm the product is AI-owned and nobody else is mid-run on it,
   claim it and `git pull`. Run the Day-1 check of the last apply (`python scripts/autonomy.py day1 ...`: a trip opens an
   alert for the book owner and Auto stays on, decision 163). Then, after current execution checks pass, run `approvals` on last week's run folder, check its
   `approved/` (`applied --folder approved --dry-run`), apply it through MAP, read every row back, record it with
   `applied --folder approved`, and run `log_invest` on it. Don't pull this week's data before last week is settled.
2. Pull the data into a run folder `runs/<ASIN>-<YYYY-MM-DD>/` (references/data-pull.md), with the live inventory every run
   (`live_keywords`, `live_targets`, `sd_targets`, `sd_campaigns`: every keyword and target is priced, leaving none behind,
   rulebook 2c, decision 135; `plan.py` stops with `need_live_inventory.json` without them, or plans with
   `--partial-inventory "<why>"`), read first the campaigns the ASIN's own ads serve in (`ad_campaigns_p1.json` SP,
   `_p2.json` SD: data-pull.md "Campaigns by product ad", decision 156; multi-ASIN campaigns are left out on purpose), and with `campaign_days.json` for the budget check (references/budget-headroom.md): a campaign that runs out of budget at an ACOS at or under 80% of the
   product's breakeven ACOS gets a +50% 'Budget step' row (Auto since 2026-10-22), and a step that stopped paying goes back.
   A rank campaign (Invest or Prove first) that runs out of budget steps up whatever its ACOS and is never stepped back for
   ACOS (decision 174): its losses are the investment; the $50/day ceiling, the step and the week between looks stay.
   Read the referral fee Amazon charged too: `settlement.json`, the last 14 days of settled orders (data-pull.md
   "Referral fee", decision 169). `plan.py` stops with `need_settlement.json` without it, and with 10+ units settled it
   moves `profit_per_unit` to that rate; when it does, say so in the run log ("referral fee now 15.0% (was 9.94%): profit
   $3.01 -> $2.61"; the Slack message carries it).
3. Save the team's decisions, then plan (it refuses without them once the product has a Bids item):
   `python scripts/dashboard.py reviews --asin <ASIN> --save <run>/reviews.json`, then
   `python scripts/plan.py --asin <ASIN> --run <run> --today <day> [--mode onboard] [--allow-volatile]` (`<day>`: today's
   date in Singapore; `--allow-volatile` only when a person has judged this week's SQP real: weekly-run.md, step 5)
   - exit 2 = fetch Amazon suggested bids for the listed searches, then rerun. Since decision 177 (2026-10-31) the list also
     holds the validated and launch-test ordinary **exact** keywords that bid the **suggested mid** (rulebook 2i), under
     `searches` (since decision 183, 2026-11-04, broad, phrase and Sponsored Brands keywords bid breakeven, so the
     `keywords` list stays empty), and the searches over the rank cap that bid the suggested low. Amazon's median first, then SoldScope's middle cost per
     click, then an estimate; the run summary's `mid_bid` lists each keyword at the mid and its 90-day test spend. A search Amazon has none for, or keeps
     rate-limiting after one retry about 5 minutes later, never stops the run: save SoldScope's estimate for it in
     `soldscope_bids.json`, write what you tried in `bid_sources_tried.json` and rerun, and the planner prices the rest
     itself (rulebook section 2, "When Amazon gives no suggested bid"; decision 106). It may also ask for business suggested
     bids (`need_suggested_bids_business.json`): read those in the B2B ad group the file names for each search (the
     owner's), or any enabled B2B ad group of the product when it names none, and save them as
     `suggested_bids_business.json` (references/data-pull.md).
   - Business rows (`owner_kind: business`, from the Amazon Business campaigns) take every role a consumer keyword can,
     and follow the same lanes, judged on the B2B keyword's own evidence: its own index, orders and clicks, its own
     locks and invest log (rulebook 9). A business invest happens inside the team's B2B campaign that holds the keyword;
     the planner never creates a B2B campaign.
   - Read `visibility_review.json` and `need_visibility_data.json` (references/visibility.md).
     Include enabled zero-activity targets, fresh recommendations for each actual match type/ad group (where Amazon
     gives one; a missing one holds only that target's visibility proposal, never the run),
     delivery windows and retained experiment history in `visibility_inputs.json`.
     Keep the existing IDX thresholds (invest at least 1.1, trim below 0.8 with sufficient evidence).
     Low-delivery Test/Discovery candidates get a finite, separately priced visibility proposal; Trim is not
     automatically rescued. Healthy economical traffic need not match Amazon's suggested low.
     Kim approved this policy on Oct 19, 2026, not unspecified per-target budgets or live bid changes.
4. Live checks (references/live-checks.md): idle duplicates, self-blocking negatives, out-of-plan spend.
   A paused snapshot is not a reason to skip the audit. Verify marketplace time and the effective dayparting rule
   (direct assignment overrides strategy). A proven scheduled OFF period permits normal base-bid planning and
   guarded bid-only execution without unpausing anything; manual/unknown pauses remain held. Use the evidence
   contract in references/visibility.md. Actual serving, replacement routing and experiment clocks remain separate checks; weekends do not delay bids.
5. Negatives: run `amazon-negative-keyword-audit` for the product; its approved table joins the plan.
6. Placements: review `placement_review` (references/placements.md): mature campaign-specific CVR,
   CPC and economics; sufficient-data modifier suggestions or explicit holds. Preserve live settings;
   new campaigns default to 0% unless a separately reviewed rank-investment experiment is proposed.
   Exception (Kim, 2026-10-20): top of search on rank-investment campaigns is standing policy,
   +50% Invest and +30% Prove first (`placement.rank_tos_standing`); rank launches take it with no
   separate approval, on the evidence ladder (the bands are information since decision 100, and there is no money level since decision 99).
   Check the product's `proposed_rank_experiments`: retain and explicitly reassess these proposals,
   never silently cancel them because mature placement evidence is thin. Keep early search evidence
   distinct from placement proof. Any other placement change needs separate launch approval; no
   automatic placement writes beyond the standing policy, the product-page base bid and down-only bidding.
   Since 2026-10-26 (decision 140): in a campaign with enough placement data, the best-converting placement keeps the
   keyword's bid and the others bid by their own conversion (the base bid drops, the modifiers raise the better
   placements back; nothing bids more than the plan priced it), and every up-and-down campaign moves to down only
   (an AMC or shared one waits for a person). Both need `placement_inputs.json` in the run folder; references/placements.md.
   Non-rank keywords and targets (Hold, Defend, Test, Discovery, audience caps) bid 100% of breakeven since 2026-10-28
   (decision 157; 85% from 2026-10-26, decision 139; rulebook 2d); rank searches, Trim and seasonal products in season keep
   their own prices. Since 2026-10-31 (decision 177, rulebook 2i) a validated ordinary keyword (Hold with 2+ orders on its
   search; Test or Discovery with 2+ orders at index 0.8 or more) and a launch-test keyword (Test or Discovery with 0-1
   orders, until 2 expected orders at the product's ad conversion, 15 to 60 clicks, or 3 with one order, at most 90;
   decision 178) bid the suggested mid instead, 75% of it in the top 10, owning copy only. A keyword in its launch test is
   not paused by the leak check.
   Needs human: first complete `references/market-research.md`: semantic query fit, sufficient-data
   IDX × search-volume opportunities, live Amazon competing offers and a reasoned price/conversion
   assessment in `<run>/market_review.json`. The AI finishes this research itself, every run; people see
   only decisions it can't make or borderline ones, as a short recommendation (`human_review.for_people`,
   decision 97). Unfinished research and monitoring stay in the product file, off every page people read.
   Route follow-ups by who can do the next action, not by an old `decision` label. Use
   `references/work-queue.md`: retain approvals, do AI preflight/research before escalation, and
   close or supersede a note only with evidence. A dashboard queue is not an execution service.
   Review the planner's `human_review` proposals; add listing/price hypotheses with evidence
   in `<run>/human_review.json` and rerun (references/needs-human.md). Every sweep considers price positioning;
   concrete prices require dated economics, comparable packs, a rollback and Kim approval. No automatic price writes.
   An enabled run has no preview to approve and no proposed publish (decision 98). A shadow product (Auto off): preview
   with `python scripts/preview.py --out <run>/preview.html <run>/plan.json`, publish it with the Artifact tool, and put
   the plan on the dashboard with `python scripts/dashboard.py publish --asin <ASIN> --run <run> --state proposed`.
   Update the product file's `brief` and `open_items`.
7. Apply `auto/` yourself during the audit (references/weekly-run.md, step 12; references/map-playbook.md for the order).
   First `python scripts/write_window.py check`: on `hold` (a Scale Insights switch under 2 hours away or under an hour
   past, decisions 151 and 152), wait until its `safe_from` or `park` the folder. Apply as soon as the run finishes, at any
   hour and any day: the switch hold is the only wait, never 10:00 SGT or office hours (decision 174). Then `write_window.py prewrite` against
   a fresh live read: `replan` means only dayparting moved bids (a weekend $1.28, × 0.8 since decision 174, back to its $1.60 base at Monday 21:00
   SGT is expected, never a stop or a question: plan again), `stop` means something else changed. After the apply,
   `write_window.py after-apply` adds the re-check when a switch is near. Then apply
   its MAP payloads through MarketplaceAdPros, its `scale_insights_steps.json` in the signed-in browser
   (references/scale-insights-playbook.md), and read back every row
   (`python scripts/autonomy.py readback ...`: a mismatch stops the folder and opens an alert, Auto stays on, decision 163). Run its check first:
   `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder auto --dry-run` (it refuses duplicate creations and a product whose Auto is off). `review/` and `approved/` still go out
   only after a person's yes.
8. Record:
   - `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder <the folder that went out> --date <day>`
     (weekly-run.md rule 5), straight after the apply and read-back, before anything else: it records what went out and
     its locks and starts the clocks. If the apply stopped part way, add `--rows "<row_id>,<row_id>"` with only the rows
     that went out;
   - `python scripts/log_invest.py --asin <ASIN> --run <run> --date <day> [--applied-harvest-bid]` (it keeps business
     invests in the product file's `business_invest_log`);
   - once the product's B2B ad groups are off the team's Scale Insights bid rules (the plan's `Scale Insights rules`
     row for "B2B ad groups", the book owner's to approve since 2026-10-22), set `business.si_rules_off` to that date in
     the product file, and add the ids of the campaigns put on the exact-owners strategy (103) to
     `business.si_exact_owners` (the row's how names them), or every run asks again. The row comes back later only for a campaign that newly holds a business invest and
     is not in `si_exact_owners`; add its id once it is moved (rulebook 9.7);
   - once a month: refresh `business.pool_prior_cvr` and `pool_prior_as_of` in `config.json` from the MAP SQL in
     references/data-pull.md ("Monthly: the B2B pool's prior"), with Kim's sign-off; the first is due 2026-11-21;
   - the dated run log `logs/<date>-<product>-weekly-run.md` in the your-ppc-repo repo (logs/README.md), then
     `python scripts/dashboard.py logs --push` so the dashboard serves it at `/logs` (references/dashboard.md,
     "Run logs on the dashboard");
   - the product file's `activity`, `open_items` and `brief` (plus `<run>/applied.json` if the apply deviated);
   - `python scripts/dashboard.py publish --asin <ASIN> --run <run> --state applied --date <day> --by "<name>"` (no
     proposed publish first), then
     `python scripts/dashboard.py refresh --asin <ASIN> --run <run>` once the run is planned for the last time: it records the
     run's SQP totals and data stage in the product file (weekly-run.md, step 14.5; rulebook 10.6);
   - "For human" and Slack (weekly-run.md, step 14.6): `python scripts/autonomy.py stock ...` when the plan flags low stock (its increases wait For human, or a person's clearance),
     then `python scripts/notify.py --asin <ASIN> --run <run> --date <day>` and post its `text` to #3d-ppc-standup
     (`channel_id` C0EXAMPLE01) with the Slack connector: the recap of what the run did, tagging the book owner, and a
     "For human" line per parked item tagging who decides;
   - commit and push the product file and the log (`git pull` before the next run): an autonomous run does it as its last
     step, and it is required whenever `approvals`, `applied` or `autonomy.py` wrote the product file (weekly-run.md rule 10).

## Files

- `config.json`: account IDs, shared SI strategy and import-rule IDs, every rulebook threshold, the shared data folder.
- `data/asins/<ASIN>.json`: per-product economics, naming prefix, relevance lists, harvest ad group, invest log.
- `scripts/plan.py`: the deterministic planner. `scripts/preview.py`: the approval page. `scripts/log_invest.py`:
  records what went live. `scripts/budget_headroom.py`: budget steps for campaigns that run out of budget at a profit,
  and for rank campaigns that run out of budget whatever their ACOS (decision 174)
  (weekly rows through plan.py; `catalog` scans the rest; `record` writes a step to `data/budget_steps.json`).
  `scripts/season.py`: seasonal products (season dates from SoldScope, the phase on a day, the dated steps; rulebook
  section 8). `scripts/blacklist_rescue.py`: keeps every Invest and Prove-first search off its product's Scale Insights
  blacklist (Kim, 2026-10-21; a step-95 row in the plan when the run folder holds `si_blacklist.json`).
  `scripts/close_variants.py`: close-variant checks for negatives. `scripts/stage.py`: a product's data stage (launch,
  early or mature) and the checks the planner makes on it (rulebook section 10). `scripts/launch_list.py`: builds the
  `launch` block from the DataDive niche (references/data-pull.md, "Launch list"). `scripts/dashboard.py`:
  builds and publishes each product's dashboard page (`refresh` republishes one from its product file, for anyone,
  any day; a publish is refused if a teammate published that page after your copy); also uploads the page and
  manages the dashboard secrets, and holds the lane commands `reviews`, `approvals` and `applied`.
  `scripts/lanes.py`, `plan_lanes.py`, `evidence.py` and `searchtext.py`: the lane rules and their helpers
  (references/data-pull.md, "The planner's modules"). `scripts/stop_loss.py`: the stop-loss step-down rows.
  `scripts/autonomy.py`: the guards of an autonomous run (Day-1 check, read-back, the kill switch, the low-stock item)
  and the program total (information only). `scripts/notify.py`: the run's one Slack message.
- `scripts/growth.py`, `references/for-growth.md`: the For Growth item, the Growth team's paste-ready listing-pass block
  (when it is raised, what is in it, the two buttons and the close); `dashboard.py growth` anchors, enables and emits it.
- `references/readiness-audit.md`: read-only pre-entry audit, isolated product draft, ownership evidence, shadow plan and report.
- `references/`: rulebook.md (the why and every formula), onboarding.md, weekly-run.md, data-pull.md,
  live-checks.md, map-playbook.md, scale-insights-playbook.md, team.md, dashboard.md.
- `assets/preview_template.html`: the approval page template.
- `dashboard/`: the Railway server (`server.ts`), the page (`site/`), its tests and a local preview script.
  Secrets never live here: they are in `~/.config/your-ppc-repo-dashboard/secrets.env`.

## What it does not cover yet

Visibility diagnostics and bounded keyword tests currently cover Sponsored Products manual keywords only.
Sponsored Products ASIN/category targets retain rulebook section 2b; Sponsored Brands video retains its existing
separate planning path. Do not reuse SP keyword bid ranges for either. Auto-targeting groups and Sponsored
Display CPC targets are priced by the planner since decision 135 (rulebook 2b), and SB product and theme targets since
decisions 155 and 156 (cut only); SD vCPM campaigns are listed for a person, not priced. Price changes require a separately reviewed `price_change`.
There is no background experiment executor: limits must be checked by the agent during approved execution
and follow-up, with attribution lag accounted for. See references/visibility.md for the shared Claude/Codex contract.
