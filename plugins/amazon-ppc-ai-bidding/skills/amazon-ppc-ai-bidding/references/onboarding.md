# Onboarding a product (once)

Moves one ASIN from Scale Insights bid rules to AI-managed bidding. Takes one session. **Any book owner adds a product to
the AI program by asking for it** ("audit <ASIN> for the AI bidding skill", "onboard <ASIN>"): no one else's approval,
no readiness audit first (Kim, 2026-10-30, decision 172: "The PPC teammates are independent humans. They also don't need
to ask Kim"; decision 96 had kept it Kim's). Record who asked in the product file's `registry.added_by` and the run log.
Kim can still take a product out. Onboarding is an autonomous run (decision 98, 2026-10-22):
the run applies its own Auto rows (the standard Scale Insights setup in the browser, then the MAP writes), records them with
`dashboard.py applied --folder auto`, publishes the result as applied and posts the run's Slack message. Only the rows it
parks "For human" (rulebook 7.9) wait for a person. Steps the planner can't write (the product file, the harvest campaign
and its seed keyword, the rank radar) are below. A rank radar within DataDive's quota needs no approval (decision 105,
section 5).

## Straight to the run (decision 172)

Go from section 1 to the end of this guide, then run the weekly run (weekly-run.md) on the product in the same session: the
keyword-by-keyword plan, each search priced on its own SQP conversion (decision 162), applied through the Auto lane. Plan on
the newest SQP there is, whatever its age; a seasonal product adds last season's SQP (data-pull.md). Don't run the
read-only check first: [readiness-audit.md](readiness-audit.md) is only for a person who explicitly asks for a read-only or
shadow look. **Shared campaigns:** the onboarding run writes the product's `ownership_scope` itself, listing every campaign
it finds shared with another ASIN as excluded (it stays with Scale Insights, untouched), and goes on with the exclusive
ones. No approval is needed for that (decision 172; decisions 109 and 111 had made each scope Kim's).

## 1. Product file

Create `<data>/asins/<ASIN>.json`; copy one of the bookmark files as a template. Fill in:

- `sku`, `product` (short name for the menu), `title`.
- `name`, `type`, `amazon_title`, `image`, `launch_source` and `monitor.prior`: see dashboard.md, "Product
  identity and the 50/50 goal". `name` says what the product is and what tells it apart ("Christian bookmarks (cross
  design)"); `type` is a group from `config.json` → `product_types`.
- `campaign_prefix`: the exact prefix the product's campaigns use, ending in `- <ASIN> - `. Read it from a live
  campaign name.
- `price` and `profit_per_unit` (price minus every cost): SI `get_product_metadata` (UnitProfit) or the
  `profit-check` skill. Set `economics_as_of` to today.
- `launch_date`: from the Monday PPC board (not the catalog).
- `budget_overrides`: the product's biggest invest search at $15, decided after the first plan.
- `relevance`: negate_phrase / negate_exact / protect / never_target. Seed it from the
  `amazon-negative-keyword-audit` fingerprint for the product (`data/fingerprints.json` there). Protect words the
  product genuinely matches (sizes, audiences, formats verified on the PDP).
- `invest_log: {}`.
- `sb_video`: `video_asset_id` (the asset on the product's live "Highest Converting Search Terms" video ad: MAP
  `list_resources sb_ads` for one of those campaigns, `creative.videoAssetIds`), `campaigns: []` (filled after each
  apply), and `budget` only to override the series' usual budget. No video at all: ask the user for one before
  planning SB.

Add the product to the registry as "onboarding" (team.md).

**Claim the product first:** `python scripts/dashboard.py claim --asin <ASIN> --what "Onboarding" --until <date>`,
and release it after step 8 (`release --asin <ASIN> --note "..."`). The dashboard shows the team who is on it.

**Lined-up products** already have a product file (`registry.stage` "queued", with `brief`, `monitor` and
`open_items`; published with `dashboard.py lineup`). Keep those fields and add the ones above. Set
`registry.stage` to "onboarding" when the run starts, and to "ai" at step 8.

## 2. Pull and plan

- Pull data per data-pull.md.
- Run `python scripts/plan.py --asin <ASIN> --run <run> --mode onboard`. Onboard mode adds step 1 (Scale
  Insights) to the preview.

### A product with no SQP yet (a new launch)

A product with fewer than 10 SQP queries with impressions has no market to plan from. The launch list stands in for it
(rulebook section 10.7, data-pull.md "Launch list").

1. Pull the niche, and Amazon's recommendations once the harvest ad group exists, as data-pull.md "Launch list" says:
   `niche_keywords.json` and `keyword_recs.json` in the run folder.
2. Run `python scripts/launch_list.py --asin <ASIN> --niche <run>/niche_keywords.json --niche-id <id> --today <day> --out
   <run>/launch_block.json` (add `--recs <run>/keyword_recs.json` once you have it). Read the table, the left-out searches
   and the proposed roots.
3. Paste the block into the product file as `launch`, once a person has set its `date` (the Monday board's launch date) and
   confirmed its `roots`. The script never writes the product file.
4. What the planner does with it:
   - While the product has a `launch` block dated within 90 days and under 10 SQP queries with impressions, it is in the
     launch stage and `plan.py` stops with a message that names the list. The team's launch structure, built by hand from
     the list, carries the first weeks. The planner plans launch mode once the launch plan's Task 3 lands
     (`docs/superpowers/plans/2026-10-20-launch-process-ai-growth.md`).
   - From the first run with 10 queries, the early rules apply (rulebook 10.1 and 10.3). So they do for a product with SQP and
     no `launch` block, which is early, never launch.
5. **Roots make the "unlisted" flag work.** The flag says a search is in none of the product's lists (rulebook 10.3, item 4).
   The planner applies it only when the product has something to be unlisted from: a launch list, a `niche_keywords.json`
   in the run, or roots (`relevance.roots`, or the `launch` block's `roots`). A product with none is checked for one-word
   searches only. The script proposes roots from the niche's rows at relevancy 0.9 or more, and a person confirms them. The
   gel pens' stage dry run (2026-10-22) used `relevance.roots: ["pens"]`: the real niche splits "colored" and "colorful" at
   relevancy 0.923, so its proposal is `pens` alone. Without roots, "gel pens for coloring" would have read as unlisted.
   A root matches its plural and singular ("fine point gel pen" is listed under `pens`, since 2026-10-22), so confirm
   word families, not spellings.

## 3. Live checks

Run all four checks in live-checks.md.

## 4. Harvest destination

- **Name the campaign** `<campaign_prefix>Harvest Exact - SI import`. The auto-assign criterion of SI strategy
  302498 matches that suffix.
- **Plan it** in the preview as: manual campaign, $5/day, portfolio from config, dynamic bids down only, top of
  search 0%.
- **Then:** ad group "Harvest Exact" with default bid = plan.json `harvest.default_bid`, plus a product ad for the
  SKU, plus **one seed exact keyword**.
  If Amazon has no ranges after the documented attempt, the planner can compute the same harvest bid and gate from
  complete, positive, ordered SoldScope low/CPC/high ranges for exact queries in this product's terms (decision 106).
  Keep `harvest.bid_source` and `priced_on` in the record. Own CPC or breakeven alone cannot supply the import gate;
  without actual ranges, leave the destination pending rather than inventing a low or high.
  - Scale Insights lists only ad groups that have a keyword or target, on every assignment page (strategy pages,
    Assigned rules, Import rule). An empty harvest ad group can never receive strategy 302498 (found on the pilot,
    2026-10-17).
  - Seed it with a search the import rule would pick anyway: 1+ order at or above the gate conversion, relevant,
    and owned by no exact campaign (check the live keyword list). Put it in the preview like any other change.
    Check its dimensions with the planner's product-size relevance gate first (rulebook section 2, 2026-10-24):
    a wrong-size search is never a seed, even with orders or a generic protect phrase.
  - **If every candidate is already an exact keyword on the product** (both pilots, 2026-10-17: the products
    carried hundreds of exact keywords in low-bid and AMC campaigns), use the placeholder exact keyword
    "harvest placeholder yourbrand" at $0.02. It never serves; it only makes the ad group visible to Scale Insights.

## 5. Rank tracking

- DataDive Rank Radar for the product, all invest and prove-first searches plus the main Hold searches.

**Rank Radar within DataDive's quota needs no approval** (Kim, 2026-10-23, decision 105: "if there are still slots
available, it goes ahead and creates them, and only asks for approval when there aren't enough slots left").
- Read DataDive `get_quota` first. `RANK_RADAR_KEYWORDS` capacity minus used is the number of free keyword slots.
- Track the product on a radar it already has before making one: `resume_rank_radar` for a paused radar of the ASIN, or
  `add_rank_radar_search_terms` to add searches. Both use slots and can be undone.
- With no radar for the ASIN and enough free slots for the keyword count, call `create_rank_radar` with `confirm: true`.
  Kim's standing approval is the user approval that tool asks for.
- Copy any `warnings` from the tool's preview word for word into the run log and the Slack recap. A warning never blocks
  creation.
- If a create call errors or times out, check `list_rank_radars` before calling again, because each call spends again.
- A Niche Dive the radar needs (`create_niche_dive`, quota `DIVED_ASINS`) follows the same rule.
- Only when the free slots are fewer than the keywords to track, park one For human item for Kim: "Rank Radar for
  <ASIN>: needs N keyword slots, F free until <nextRefreshDate>".
- An open "Rank Radar tokens" approval item from before decision 105 is no longer a decision: the run creates the radar
  within quota and closes the item.

- Store the radar id in the product file (`rank_radar_id`).

## 6. The plan, and what waits for a person

- Read `plan.json`: the Auto rows apply on their own (step 8), the "For human" rows go on the run's Bids item, and the
  harvest destination (step 4) is built by hand as the plan says.
- A preview is needed only when the product's Auto is off (its product file says `"auto": {"enabled": false}`): then build
  `python scripts/preview.py --out <run>/preview.html <run>/plan.json`, publish it as an Artifact, list the Scale Insights
  steps (7 below) and the harvest destination in your message, and wait for the user's approval.
- Until 2026-10-22 every onboarding waited for that approval.

## 7. Scale Insights, in Chrome (before any MAP write, except the hours, which open last)

Mechanics are in scale-insights-playbook.md. The plan's step-1 "Scale Insights rules" row (and any "Scale Insights setup"
row) is in `payloads/auto/scale_insights_steps.json`: the standard AI setup, applied by the run itself in the signed-in
browser (a person signs in; the agent never types a password). A step the browser can't do goes to the run's "For human"
items for the book owner. A rule set beyond the standard setup below is Kim's.

**Scope check before the first assignment (2026-10-23).** Keep the full Assigned and Unassigned CSV downloads,
then inspect the Bidding rule page's Sponsored Brands rows for the ASIN, including Product Collection ads.
Mixed-ASIN creatives can have a blank `Associated ASIN` in the export and be absent from strategy grids, while
the browser's ASIN search still matches them. An exact-ASIN CSV slice with zero unassigned rows does not prove
the whole product's ownership handoff. Check each matched row's actual advertised ASINs and campaign/ad-group
IDs; a campaign name alone is not association evidence. Never bulk-unassign all ASIN-search matches: select
only the verified exclusive IDs. Shared campaigns and all descendants remain untouched. When the onboarding run has written
their exact exclusions in `ownership_scope` (decision 172), their legacy SI rules and paused states are intentional: they do not
make exclusive onboarding partial or incomplete, create a pending action, or trip the Auto ownership guard.
Complete and assess the authorized exclusive handoff independently. When fresh membership reveals a new shared campaign, add it to `ownership_scope` as excluded in the same
run and go on (decision 172). Do not describe an excluded shared campaign as transferred to AI.

**Explain new-group SI synchronization plainly (2026-10-24).** Amazon creation and SI visibility are separate.
A verified new Amazon ad-group ID may not yet appear in SI's imported inventory and assignment pages. Record
the exact exclusive IDs still absent, the last SGT check and the next required protection/import assignment;
do not recreate the groups or promise a fixed sync time. Once visible, assign and independently verify the
required strategy/import rules before clearing that gate. Report this as "new exclusive groups created on
Amazon; waiting for Scale Insights to import them so protection rules can be assigned and verified".
This is genuine exclusive work still pending, unrelated to approved shared exclusions. Preserve all independent
moderation, actual-serving, negative-clearance and readback checks, and distinguish already applied bid changes
from these new-group follow-ups.

1. **Bid rules off, guardrails on.** Strategy names start with their number (renamed 2026-10-17; the IDs are in
   config.json `scale_insights`). **Every product moved to AI bidding comes off its legacy Scale Insights strategies
   and rules onto these AI objectives; none stays on "Scale Insights rules"** (Kim, 2026-11-04, decision 180).
   Shared campaigns and groups listed as shared in `ownership_scope` keep their current setup.
   - Keyword targeting page: filter AssociatedASIN = product. Assign every keyword ad group to 101 / 302489 (or
     102 / 302490 for audience / low-bid ad groups).
   - Do the same on the Auto (111 / 302491), Product targeting (121 / 302492), Video (141 / 302494, 142 / 302495,
     143 / 302496) and Display (131 / 302493) pages. Exact SKCs and exact owners go on 103 / 302497 and SB video exact
     owners on 144 / 302500, with the blacklist unassigned; harvest groups on 104 / 302498 or 105 / 302499.
   - Verify on Assigned rules that the only BidFilter is "202 Brake", and only on 101, 111 and 121 ad groups.
   - **Dayparting (Kim, 2026-10-24):** standard onboarding assigns **203 Optimum Hours, weekends on with
     bids -20% (21246)** (−20% since 2026-10-31, decision 174; −15% when this was written) to every AI-controlled
     SP, SB and SD ad group, including low-bid/audience groups.
     Replace legacy direct product schedules ("708. …", Rainbow's 260, Minimal hours, etc.) on verified
     exclusive IDs; do not keep them simply because the new strategy also lists Optimum Hours. Assign 21246
     directly when an override would otherwise survive. This is authorized standard setup and needs no
     additional dayparting approval once the product's onboarding is authorized.
     Preserve approved shared-campaign exclusions and explicitly approved experiment/custom schedules; record
     their exact IDs and authorization. Do not edit a shared rule's definition or bulk-change a product-wide
     schedule that also reaches excluded campaigns. Verify the effective rule via fresh direct `RuleIdList`
     plus strategy IDs on all three ad formats, and save exact-ID coverage and exceptions. Missing or conflicting
     exclusive-group coverage remains a genuine onboarding follow-up. Check new harvest/rank/video groups again
     after SI imports them; strategy assignment alone is not proof of effective 203 coverage. This changes hours,
     not eligibility: independent manual-pause, moderation, ownership and buyability guards remain.
   - **The hours open last (Kim, 2026-10-25, decision 135).** Take the bid rules off first, as above, but leave a
     legacy direct schedule ("5–6am only", Minimal hours, …) in place until every MAP bid of the plan is written and read
     back (section 8). Then replace it with 21246 in the same session, before Scale Insights' nightly run (about 02:10
     SGT), and verify it as above. Why: on the Oct 21 onboardings a campaign the old schedule held to an hour a day spent
     all day at its old Scale Insights bid once 203 opened it (the AI spend review, 2026-10-25: one keyword bid $1.11
     against a $0.39 breakeven). The plan now prices every keyword and target first (rulebook 2c), so the hours open on AI
     bids.
2. **Exact SKCs own their search.**
   - Filter CampaignName contains "Exact SKC" and assign 302497 (no blacklist, no negative rules, Optimum Hours).
   - Then on the Blacklist/whitelist rule page, select the same ad groups and **Unassign rules**: the blacklist is
     attached per ad group and survives the strategy change.
   - Verify: SKCs show no blacklist and no negative rule.
3. **Whitelist and blacklist rescue.** Add every invest and prove-first search to the product's exact whitelist
   (BlacklistRule/Edit?asin=…, ExactWhiteList), and take off the blacklist every entry that blocks one: the search
   itself, a close variant, or a phrase inside it (Kim, 2026-10-21). Read the lists into `si_blacklist.json` before
   planning; the plan then carries the rescue as a "Scale Insights setup" row. Re-read after save.
   (scale-insights-playbook.md, "Blacklist rescue".)
4. **Harvest.**
   - Wait for SI to sync the harvest campaign (often about an hour; "Refresh ads" helps). The ad group appears
     only once it has its seed keyword (step 4).
   - Assign strategy 302498 to its ad group on the Keyword targeting page.
   - Verify on Assigned rules that ImportFilter shows the gate band's import rule.
   - Don't use "Automate assignment" to do it.

## 8. MAP writes

During the audit on any day, check first: `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder auto --dry-run`. Weekends and legacy Monday dates do not defer eligible writes (Kim, decision 114).
Apply `payloads/auto/` in order per map-playbook.md and read back every row (weekly-run.md, "Read back every row";
`python scripts/autonomy.py readback ...` stops the folder's remaining writes and opens a "Read-back" alert on a
mismatch; Auto stays on, decision 163). Then, straight away:

- open the hours: replace the legacy direct schedules with 21246 and verify the coverage (section 7, step 1, "The hours open
  last");

- record what went out, the Scale Insights steps of step 7 included:
  `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder auto --date <day>` (add `--rows` when only part
  went out). Until 2026-10-22 onboarding never ran `applied`; now its rows are recorded like any run's, so its creations are
  create-locked and its promotions start their stop-loss clocks on the day they went out;
- run `python scripts/log_invest.py --asin <ASIN> --run <run> --date <day> --applied-harvest-bid`;
- set the registry to "AI" (product file: `registry.stage` "ai", `bid_owner` "AI");
- write the dated run log;
- fill the product file's dashboard fields:
  - `registry`: `bid_owner` "AI", `owner_since`, `run_by`, `weekday`, `next_run`;
  - `baseline`: the category rank at launch;
  - `brief`, `open_items`, `activity`, and `reviews` at 4 and 8 weeks;
  - `harvest.active` and `harvest.strategy_status`;
  - `growth.anchor` and `growth.next_pass`: `python scripts/dashboard.py growth --asin <ASIN> --anchor --clicks-daily
    <run>/clicks_daily.json` (weekly-run.md, "For Growth: the anchor and the switch"). Then switch For Growth on:
    `python scripts/dashboard.py growth --asin <ASIN> --enable --by "<name>"` (decision 166: every AI product; the first
    publish does it anyway when it was missed);
- publish the product: `python scripts/dashboard.py publish --asin <ASIN> --run <run> --state applied --label
  "Launch (onboarding)" --by "<name>"` (dashboard.md);
- post the run's Slack message: `python scripts/notify.py --asin <ASIN> --run <run> --date <day>`, its `text` to its
  `channel_id` (#3d-ppc-standup) with the Slack connector (weekly-run.md, step 14.6);
- commit and push the product file and the run log.

## 9. Day-1 check

24 hours later, or at the start of the next run: `python scripts/autonomy.py day1 ...` (weekly-run.md, "Day-1 check"). A
spend trip opens an alert for the book owner; Auto stays on (decision 163, 2026-10-29; it switched Auto off before).

## Several products in one session (learned 2026-10-17, eight products)

- **Pulls in parallel:** one read-only subagent per two products, each saving into its own run folder. The agents share
  one tool-results folder, so each must match a saved file to its ASIN by content (the SQP payload's ASIN, campaign
  names) before copying it. Check afterwards that every run file names only its own ASIN.
- **Suggested bids one ad group at a time.** Amazon's bid-recommendation limit refills slowly: parallel calls fail, and
  a failed call needs about 5 minutes before the next.
- **Relevance lists:** seed from the negative-audit fingerprint's NEGATE tokens (minus the converter-shielded ones, which
  go to protect). A product without a fingerprint borrows its sister product's list, without format words that weren't
  checked on the product page.
- **Scale Insights before the nightly run.** Strategy assignment can be scripted per page: read the assignment grid for
  all the products' ASINs, group ad groups by target strategy, then filter the grid to 100 ad group IDs at a time, tick
  the header box, set `#StrategyId` and click Assign (no dialog). Verify on Assigned rules: 0 unassigned, the only
  BidFilter "202 Brake" on 101/111/121.
- **Gate bands without an import rule:** a lower band (5%, 7%) can use the 9% rule 201, which only imports fewer
  searches. A higher band (12%) waits for its own rule: at 9% it would import searches that lose money at the starting
  bid. Create the harvest campaign anyway; leave its strategy until the rule exists.
- **Apply in parallel:** one subagent per two products, each following a written brief (step order, payload files,
  verification, `apply_result.json`). Read every result file before recording anything.
