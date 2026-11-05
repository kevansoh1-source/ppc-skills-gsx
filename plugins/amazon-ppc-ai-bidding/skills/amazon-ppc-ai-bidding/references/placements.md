# Placement recommendations (2026-10-18 SGT)

Kim requested campaign-level placement analysis in every routine sweep, with sufficient-data
recommendations, otherwise holds, and a preview before applying. This implementation is
**recommendation-only**. The numerical policy below is proposed for Kim's approval, not a
previously signed-off rule. Never execute its suggestions as part of an old approval.

## Evidence and scope

Use MAP `sponsored_products_campaign_placements`, grouped by campaign ID and
`placementClassification`; SUM(clicks), SUM(purchases14d), SUM(cost), SUM(sales14d).
CVR uses purchases, not units. Campaign placements cannot be attributed to individual keywords
in a multi-keyword campaign, nor provide a market placement CVR. SQP index remains separate.
Product-ad ownership identifies the advertised product, not necessarily every purchased ASIN.

Use a mature 30-day decision window ending 15 calendar days before the SGT pull date, then a
mature 90-day fallback with the same end date. Recent 30 days through yesterday are context
only because purchases may still accrue. Report dates remain in the US profile's calendar.
For 2026-10-18: Sep 4–Oct 3, Jul 6–Oct 3, recent Sep 18–Oct 17.

Join report ownership from `sponsored_products_product_ads`: count DISTINCT advertisedAsin
over the whole reporting span and retain only campaigns exclusively observed for this ASIN.
Also read current product ads (enabled and paused) for all enabled campaigns and hold any
shared/unverified campaign. Read all live SP campaigns and every page; never assume missing
placement settings mean zero unless the returned bidAdjustments object confirms no adjustment.
This placement-economics sweep leaves AMC/low-bid/audience campaigns' placement boosts alone (their audience boost
compounds on the bid). The run still moves those campaigns to down-only bidding on its own ("Down-only bidding" below,
decision 155) and prices their bids around the boost (decision 156). Amazon Business (B2B) campaigns (`siteRestrictions: AMAZON_BUSINESS`
or the `B2B` name marker) are judged like any other (Kim, 2026-10-21 evening; rulebook 9.5). A B2B campaign with a
business invest this run, or one already live, is `changing`: its Business invest row sets its top of search and
budget, so it gets no second proposal. One with only Hold or Trim keywords may get a placement-economics proposal, which is
information only: since decision 155 the run's placement policy sets non-rank top of search to 0% and the placement
shape (decision 140) sets product-page bids on its own, so nobody needs to act on the proposal (Kim, 2026-10-31). Up/down, rule-based and global campaigns require
separate effective-bid review. Do not change their strategy to make this calculation work. (Since 2026-10-26, decision 140,
a live up-and-down campaign gets its own "Bidding strategy" row to move it to down only: "Down-only bidding" below. That
row is the strategy change, not a step of this calculation.)

## Planner input

Save raw responses in the run folder. Normalize to `placement_inputs.json`:

- `asin`, `as_of` (SGT YYYY-MM-DD), `retrieved_at` (offset timestamp), `complete: true` only after every page.
- `windows`: `30d`, `90d`, `recent`, each `[start, end]` inclusive.
- `campaigns`: complete live SP campaign objects from MAP.
- `live_asins`: campaign ID string → distinct current advertised ASIN strings, enabled and paused ads.
- `rows`: one exclusive-ASIN campaign/placement row. Fields: `asin`, `campaignId`, `campaign_name`,
  `placement`; `clicks30`, `orders30`, `spend30`, `sales30`; equivalent `90` and `_recent` suffixes.
  No pagination truncation or duplicate campaign/placement rows. Preserve IDs as strings.
- `source_files`: raw file names. Use `orders` aliases for SUM(purchases14d), `spend` for SUM(cost).

Missing input means hold, never a default +50%/+30% boost (the standing rank policy below does not
depend on this input). Wrong-ASIN, immature, duplicate or invalid data fails the run. `scripts/placement_review.py` implements the input and policy;
`plan.py` attaches `placement_review`, which the approval page and dashboard both display.

## Proposed experimental policy

### Separate rank-investment track (Kim, 2026-10-18 SGT)

**Standing policy since 2026-10-20 SGT (Kim: "I want it to be launched and updated on the
dashboard", not approved modifier by modifier).** Top of search on rank-investment campaigns is
+50% Invest and +30% Prove first (`placement.invest_tos_pct` / `prove_tos_pct`, switched on by
`placement.rank_tos_standing`). `placement_review.hold_defaults` then keeps the planner's TOS on those
rows instead of zeroing or holding it: a new campaign is created at it, and a reused or budget row sets
top of search to it and carries the live rest-of-search, product-page and Business modifiers unchanged.
A `Business invest` row is treated like a reused one (2026-10-21, rulebook 9.5): its B2B campaign's top of search goes
to the policy, at the highest policy among the campaign's business invests. No separate approval; the evidence ladder
decides Auto or Needs human (rulebook 7; the investment bands and Kim's $600 a month a product did too until decisions
99 and 100, 2026-10-22, made money information, not a gate).
Left as they are: a campaign whose name carries a placement experiment ("TOS 900%"), a live campaign
on up-and-down bidding or with audience adjustments, and a campaign whose live settings were not read; `placement_note` says which. The
placement-economics review below still runs for every other campaign and placement, and holds a
campaign whose top of search the plan sets. Flag off: everything below applies as written.

Kim restored the previous 30 +50% TOS proposals for the five reviewed ASINs as experiments
on related searches with early conversion evidence. Publication only; not launch approval.
These are distinct from the mature placement-economics policy below. Thin placement data is
an uncertainty to display, not an automatic veto on a deliberately proposed rank investment.
The per-product `proposed_rank_experiments` block records the exact searches, early samples,
source/window and approval boundary. Reassess it explicitly in every subsequent sweep; show
any proposed removal and why rather than silently zeroing it. Do not extend +50% beyond rank-investment campaigns.

The restored run lives in `runs/<ASIN>-2026-10-18/rank-investment-restored/`; its placement review
keeps the baseline economics rows unchanged and exposes `rank_experiments` separately. The
restoration generates no executable payloads. Rebuild any apply payload only after launch
approval and current-state checks; do not execute older folders' payloads. Require relevance,
exclusive exact ownership, an investment/loss ceiling, review timing from actual launch and
rollback conditions. Retain the negative-audit and SI onboarding gates. TOS is campaign-level,
not a per-keyword modifier. Early overall CVR does not prove TOS superiority.

### Mature placement-economics track

All constants live in `config.json` → `placement.recommendations`:

1. At least 30 clicks and 3 purchases in mature 30 days; otherwise 50 clicks and 5 purchases
   in mature 90 days, with at least 10 recent clicks. These are operational minima, not a
   statistical-significance claim. Zero-purchase samples meeting the click gate permit
   reductions only, never increases.
2. Shrink placement CVR with the existing 10-click prior toward the same campaign's pooled
   on-Amazon CVR in the same window. Breakeven CPC = current contribution/order × shrunk CVR.
3. Target modifier = `(1 + current/100) × breakeven_CPC / observed_CPC × 100 − 100`.
   This assumes fixed base bids and linear CPC response; it is a test scenario, not a forecast.
   Hold within ±10% of breakeven. Bound tests to ±25 percentage points; no new positive
   modifier above 100%; round toward current in 5-point steps. Amazon disallows negatives.
4. If already at 0% and unprofitable, hold the modifier and review base bids/offer separately.
   Do not manufacture a boost because the placement converts better than another placement. (The product-page base bid
   below does raise modifiers, but only after lowering the base bid by the same share, so no placement bids more than the
   plan priced it. It is a different mechanism with its own approval, decision 140.)
   Rank-investment allowances need explicit separate approval; the engine does not invent one.
5. Hold when the same plan changes campaign base bids, keyword ownership or routing. These
   alter auction/traffic mix; collect post-change mature data before a placement experiment.
   Hold when recent economics contradict the older recommendation. Recheck economics within
   seven days and campaign snapshots within two days; live re-read remains mandatory at apply.
6. Review after 28 days (two delivery weeks plus attribution), with the old modifier retained
   for rollback. Restore it only after approval if mature acquisition cost exceeds contribution
   or the separately approved invest allowance. No automatic rollback writes.

## Product-page base bid (Kim, 2026-10-26, decision 140)

Kim, 2026-10-26 about 00:30 SGT: "it sounds good. let's try this to build 1 and 2 as you suggest". Built in
`scripts/placement_shape.py`; settings in `config.json` → `placement.shape`.

**Why.** A keyword has one bid for every placement, priced on its blended conversion, so it overpays where it converts
worst. On the AI products, Oct 18 to 24, 2026 (US profile dates), product pages converted 8.4% against 15.1% at the top of
search and ran at 91% ACOS. Amazon only lets a placement modifier go up (0% to 900%), never down, so the only way to bid
less on product pages is to lower the base bid and raise the other placements back.

**What it does, campaign by campaign:**

1. Each placement's conversion over the mature window (`window`, 90 days by default) from `placement_inputs.json`,
   shrunk toward the campaign's own pooled conversion by `prior_clicks` (30) clicks:
   `cvr = (orders + 30 × pooled) / (clicks + 30)`.
2. The placement that converts best keeps the keyword's bid as the plan priced it (share 1). Each other placement's share
   is its conversion against the best one, never under `min_share` (0.5).
3. A rank campaign (an Invest or Prove-first search's own campaign) keeps its full standing-policy top of search: its top
   of search target is 1 + the policy (1.5 Invest, 1.3 Prove first), not 1.
4. The base share `s` is the lowest target. Every serving bid of the campaign is written at `floor_cents(bid × s)`, and
   each placement's modifier is `floor((target / s − 1) × 100)`, clamped to 0..900. Everything rounds down, so no
   placement bids more than the plan priced it.
5. The modifiers are always computed from 0% (or the rank policy), never from the live modifiers, so the shape does not
   compound week after week.

**When it is written** (else `summary.placement_shape.skipped` says why, campaign by campaign):

- The run: Auto on (not a shadow run), fresh data, the live keywords and targets read (not `--partial-inventory`), and a
  complete `placement_inputs.json` for this product at most `recommendations.max_snapshot_age_days` (2) days old.
- The campaign: a live Sponsored Products campaign this product has alone (its live product ads), not global, not an
  audience (AMC, low-bid) copy, not Amazon Business, not the harvest campaign, no placement experiment in its name, on
  down-only, up-and-down or fixed bidding, and outside the product's `ownership_scope` exclusions.
- The plan writes nothing else to the campaign itself this run (no budget, top of search, budget step, new or reused
  exact campaign, business invest or new exact keyword row). Such a campaign is shaped on a later run.
- Every row of the campaign is in the Auto lane or held by the planner this run (Monitor, with no person's decision or
  ownership boundary behind it), and every serving keyword and target has a bid the plan knows: none on its ad group's
  default bid, none kept at its live bid by a Keep marker or a review. A row for a person, or one a person's decision
  locks, leaves the campaign unshaped. (Since 2026-10-26: the first rollout plan, B0SAMP0014, held a row in every
  campaign, mostly raises past the run's 20, so nothing was shaped.) A held row writes nothing, so its keyword or target
  keeps serving at its live bid, a held pause too: the shape prices it from that live bid in a shape-only row of its own
  (`held_row_id` names the held row, which stays in `held/`).
- At least `min_campaign_clicks` (50) and `min_campaign_orders` (5) in the window, some placement cut by at least
  `min_cut` (10%), and a base bid of at least `min_base_bid` ($0.02).

**What it writes.** Each serving bid of a shaped campaign at its shaped base (`shape_base`; `plan.as_written` writes it):
a bid row the plan already had gains it, and a keyword or target whose bid the plan keeps gains a shape-only row of its own
(Auto lane). The campaign gets one "Placement shape" row (Auto lane), written as `9c_placement_shape.json`: MAP's
`optimizations.bidSettings` shape at `SALES_DOWN_ONLY`, every live placement sent (Business and any other placement
unchanged), the three it shapes at their new modifiers. An Auto "Bidding strategy" row of the same campaign is folded into
it, since the shape writes down-only bidding too.

**Apply order.** `9c_placement_shape.json` goes last, after every bid file has gone out and read back. Write a campaign's
shape only when every bid and pause row of that campaign read back as written: a shape over the old base bids would
raise top of search above the plan's price. If any of its bids failed, skip that campaign's shape and say so in the run log.

**Reading it.** The row carries `modifiers` and `modifiers_now`, `base_share`, `placement_cvr` and `rank_tos`; each bid row
carries `shape_share` and `shape_row_id`, and its WHY says the bid is the product-page base bid. The Slack recap counts the
campaigns shaped and the bids lowered for product pages.

**Measure** around Nov 1 to 2, 2026: product-page ACOS and orders on shaped campaigns against the Oct 18 to 24 baseline,
and top of search impressions share unchanged (open items).

## Down-only bidding (Kim, 2026-10-26, decision 140)

Every live Sponsored Products campaign of an AI product on up-and-down bidding (`SALES_UP_AND_DOWN`) gets a "Bidding
strategy" row to move it to down only (`SALES_DOWN_ONLY`), its placement and audience adjustments resent exactly as live.
Up and down lets Amazon raise a bid by up to 100% at the top of search and 50% elsewhere, which spends past the plan's
price; down only can only lower a bid in an auction. Fixed bids (`MANUAL`) never raise a bid and are left as they are.
Global campaigns are left alone. `placement_review.strategy_rows` builds the rows; `config.json` → `placement.down_only`.

- **Auto** when the campaign is shown to advertise this product alone (`placement_inputs.json`'s `live_asins`).
- **For human** when it is shared or its product ads were not read. An audience (AMC, low-bid) campaign moves **on its
  own** since decision 155 (2026-10-27, `placement.down_only.audience_auto`): down only can only lower a bid. Until then
  it was a person's (decision 107). The item names the campaign and its live strategy.
- Payload `5b_bidding_strategy.json`, right after the campaign updates: one `sp_campaigns` update per campaign,
  `optimizations.bidSettings` with `bidStrategy: SALES_DOWN_ONLY` and the live `bidAdjustments` unchanged. Read back
  `bidStrategy` and every placement and audience percentage.

## Placement policy (Kim, 2026-10-27, decision 155)

`config.json` → `placement.policy` (`enabled`, `non_rank_tos_pct` 0, `boost_aware`, approved by Kim). Before the bid rows,
the planner sorts every enabled or paused campaign of the product:

| Campaign | Top of search | Its bids |
|---|---|---|
| Rank: the exact SKC of an invest search (any action, held or deferred too), a retained or season rank search, a B2B invest owner | The invest policy: +50% Invest, +30% Prove first (rulebook 7.5) | Priced by role |
| Not rank, boost above 0%, settings read, down only, no audience adjustments | **0%**, on its own ("Budget and top of search", `placement_policy`, Auto). The "TOS 900%" experiments end here | Priced by role (the boost comes off in the same run) |
| Not rank, boost above 0%, but the boost can't come off this run (settings not read, global, still up-and-down, audience adjustments) | Kept as live; up-and-down campaigns get their down-only row this run, so the next run sets 0% | Every non-rank bid at **price / (1 + boost)** (`priced_bid`, `boost_kept`), never under $0.02 |
| An overnight test original named in `placement.shape.experiment_files` | Left alone | Priced by role |
| An overnight test copy (`ON80 |` or `ON50 |` in its name, `experiment_name_markers`) | Left alone | Left alone: every row on it is held (`experiment_hold`, held/), since the test's own thread sets its bids (2026-11-04) |

A shaped campaign (2e, decision 140) is not an exception to this: the shape starts from 0%, lowers the base to the worst placement's share and raises the better ones back, top of search included, so a non-rank campaign can end with a top-of-search modifier (+28% on the 50-pack, 2026-10-31) while no placement bids more than its price. That is the planner's own Auto row (`9c_placement_shape.json`, written last); it needs no one's approval. (rulebook 2h, item 1)

The row sends the budget unchanged and every live placement (the policy's top of search, the others as read), with
`dynamicBidding` `LEGACY_FOR_SALES` (down only). A paused campaign is set too, so turning it back on starts at the policy.
`summary.placement_policy` lists the campaigns in each group; the coverage ledger reads it.

### The audience boost (Kim, 2026-10-27, decision 156: "Price the bid around the boost")

An audience bid adjustment (`optimizations.bidSettings.bidAdjustments.audienceBidAdjustments`) multiplies the bid for the
shoppers in that audience. On the "AMC - Low Bids 0.25" campaigns it is +240% to +300%, so a $0.25 bid paid about $0.85 a
click, and $1.33 to $1.75 once their top-of-search boost applied too (the clicks Kim asked about on 2026-10-27). The
planner keeps the adjustment (it is the audience the campaign was built for) and prices around it, as it does a kept
top-of-search boost:

- every non-rank bid in the campaign is **price / ((1 + kept top of search) x (1 + its largest audience boost))**, never
  under $0.02; `priced_bid` is the price, `boost_kept` the combined boost in percent, and the row's why names both
  ("the campaign keeps a +30% top-of-search and +255% audience boosts").
- a rank bid is not divided: a rank search is bought to be seen (rulebook 7.5).
- it covers keywords, product and auto targets, paused rows and the ad-group default bids. Sponsored Brands audience
  boosts and the product-page and rest-of-search modifiers stay as live: not priced around.

`config.json` → `placement.audience.price_around` (on); `summary.placement_policy.audience_boost` lists the campaigns and
their boost. Off, the bids are priced as if there were no audience boost, as before 2026-10-27.

## Preview / apply boundary

New campaigns without campaign-specific evidence start at 0% for all placements in the new
preview. Existing campaign modifiers are held; budget-only payloads omit bidding settings
entirely. The +50% Invest / +30% Prove-first values are not automatic when recommendation mode
is enabled, except for rank-investment campaigns under the standing policy (above): those payloads
write top of search at the policy and the other placements as live. No other modifier suggestion
is emitted into executable payloads. Approving the base-bid list does not approve placement experiments.

After explicit approval of a modifier row, re-read the live campaign, all base bids, product ads,
audience/Business boosts and dynamic strategy. If anything changes the recommendation, re-preview.
MAP accepts the full `optimizations.bidSettings` shape: copy all existing placement and audience
entries and the strategy, change only approved percentages, preserve Business and other placements.
Do not send both optimizations and dynamicBidding. Verify returned/live values, then publish the
applied dashboard and record the change set and review/rollback dates. Price/listing reviews remain
under Needs human, separate from this bidding section. Dashboard deployment/publication needs approval too.
