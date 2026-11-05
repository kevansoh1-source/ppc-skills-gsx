# Rulebook (signed off 2026-10-17)

Every number below lives in `config.json` (`thresholds`, `placement`, `budgets`, `harvest`; section 10's in `stage`,
`fallback`, `discovery` and `launch`). Change it there.
`scripts/plan.py` implements exactly this; if you change a rule, change the script and this page together.

**Today's rules in plain words, without the history:** [references/rules-today.md](../references/rules-today.md)
(updated 2026-10-31, decisions 174, 175 and 177). This page keeps the full detail and the dated record; where an older
paragraph here disagrees with a newer dated decision, the newer one wins. Change both together.

## 1. How well does a search convert for us? (the index)

- **Index = our conversion ÷ the market's conversion on the same search.**
- Our conversion comes from SQP first (all our clicks on the search, ads and organic), when SQP shows 10+ of our
  clicks. Otherwise from the search-term report (ad clicks), when it has 10+ clicks or 3+ orders. Thinner data is
  used but not trusted for Invest, Hold or Trim.
- Thin data is shrunk toward the market: `cvr = (purchases + 10 × market) / (clicks + 10)`. One lucky order can't
  make a search look like a winner.
- Market conversion = SQP total purchases ÷ total clicks for that search, shrunk toward the product's click-weighted
  market conversion with a 20-click prior (`market_prior_clicks`); if SQP has nothing, the product's market conversion.
  Added 2026-10-17: unshrunk, a search with 1 purchase on 1 click read as a 100% market and its Test bid became the
  whole profit per order.

**Evidence correction, 2026-10-19 SGT:** a product-level prior can support a provisional bid, but it is not a
same-query market benchmark. If the query has no usable market clicks/purchases, its market-relative IDX is
**unknown**, not a ratio against the product average. Keep its own clicks, orders, smoothed conversion and
economics visible; use finite validation rather than claiming that it beats or trails the market. The existing
boundaries remain: a trusted same-query IDX **at least 1.1** supports amplification, subject to the existing
relevance, volume and organic-coverage gates; IDX **below 0.8** supports Trim only with sufficient evidence.
Exactly 0.8 stays Hold and exactly 1.1 qualifies for the stronger role when its other gates pass.
An absent purchase count is not zero: explicit zero market purchases with positive market clicks is valid observed
evidence for smoothing, while zero market clicks or a missing purchase count leaves the benchmark unavailable.

**Added 2026-10-22:** The product-market fallback (a search with no SQP row, judged against the product's market
conversion) supports Prove first only, in the early stage: section 10.

## 2. Roles

**Placement preview revision, 2026-10-18:** Kim requested evidence-based placement reviews.
When `placement.recommendations.enabled` is true, the legacy +50%/+30% defaults in the table
below are superseded in newly generated previews: new campaigns start at 0%, existing modifiers
hold, and any campaign-specific test is a separate recommendation. Numerical experiment gates
and caps are proposed, pending Kim's approval; see [placements.md](placements.md).

**Correction, 2026-10-18 SGT (Kim):** the neutral baseline above must not silently replace
separately reviewed rank-investment proposals. The five-ASIN review restores 30 previous +50%
TOS suggestions for related searches with early conversion evidence, shown separately from
placement-economics holds. This is proposal restoration, not approval to launch or a blanket
change to numerical placement thresholds. Preserve/reassess `proposed_rank_experiments` each run.

**Standing policy, 2026-10-20 SGT (Kim), which supersedes both notes above for rank-investment
campaigns:** top of search is +50% Invest and +30% Prove first (`placement.invest_tos_pct` /
`prove_tos_pct`, switched on by `placement.rank_tos_standing`). A new rank campaign is created at it and a
live one is set to it, with no separate approval. The evidence ladder (7.1) decides whether the promotion is Auto or
Needs human (the investment bands and Kim's $600 a month a product did too until decisions 99 and 100, 2026-10-22, made money
information, not a gate: 7.5, 7.7).
Rest of search, product pages and Business keep their live modifiers (0% on a new campaign). Left as
they are: campaigns whose name carries a placement experiment ("TOS 900%"), and live campaigns on
up-and-down bidding or with audience adjustments. Every other campaign and placement stays under the
placement-economics review. With the flag off, the 2026-10-18 rule above applies again.

| Role | Which searches | Bid | Campaign |
|---|---|---|---|
| **Invest** | Relevant, trusted index ≥ 1.1 (section 10 for the stages), 150+ searches in 12 weeks, 3+ purchases (SQP or ads: the higher of the two, never added, decision 174) | Amazon's suggested **median**, or the search's breakeven if higher, never above the suggested **high**. No Amazon suggestion: SoldScope's estimate, else an estimate, else 1.5 × breakeven (below the table; decision 106) | Its own exact campaign, $10/day ($15 on the product's biggest invest search), top of search +50% (standing policy since 2026-10-20) |
| **Prove first** | Same, but fewer than 3 purchases. Since 2026-10-31 (decision 174) the ladder's bar is **2 orders at index ≥ 1.1** (7.1; 1.1 since decision 178, 1.25 that morning): validated = 2+ orders, counted as the higher of the search's SQP purchases and its search-term report ad orders. In the early stage a search with no SQP row can be Prove first too, on the search-term fallback (section 10.3), at 2 ad orders. From 2026-10-25 to 2026-10-31 (decision 135) the bar was 3 orders, so an ordinary search waited for its third order and went straight to Invest | Same as Invest | Its own single-keyword exact campaign, $5/day, top of search +30% (standing policy since 2026-10-20), and its SB video. 3 orders at index ≥ 1.1 → Invest; ~30 clicks with no order → Trim |
| **Defend** | Trusted index ≥ 1.1 but small, or already ≥ 10% impression share and ≥ 50% organic | Breakeven (section 2d: 100% since 2026-10-28, decision 157; 85% from 2026-10-26 to 10-28) | Wherever it is; no extra push |
| **Hold** | Trusted index 0.8–1.1 | With 2+ orders on its search: the **suggested mid** since 2026-10-31 (section 2i, decision 177). Otherwise the breakeven click (section 2d: 100% since 2026-10-28, decision 157; 85% from 2026-10-26 to 10-28); breakeven click = profit per order × the keyword's conversion (the +15% Hold uplift test at index 1.0–1.1, decision 108, ended on 2026-10-25, below) | Bid set weekly |
| **Trim** | Trusted index < 0.8 on 15+ clicks | 70% of its own breakeven (min $0.10); **pause** below index 0.5 on 30+ clicks. Kept as is on 2026-10-31 (decision 175): its breakeven is already priced on its weaker conversion | Bid set weekly |
| **Test** | Too little trusted same-query evidence to judge, but 150+ searches or 1+ ad order. Since 2026-10-31 (decision 177) 2+ orders validate it before it is trusted: index ≥ 1.1 → Prove first (on 150+ searches; 1.1 since decision 178), under 0.8 → Trim | The **suggested mid** in its launch test (0–1 orders) and once validated at index 0.8 or more (section 2i, decisions 177 and 178). Otherwise a provisional market-conversion-based breakeven, at least $0.35 but never above the keyword's own breakeven click (since 2026-10-25, decision 135: the floor was twice a $1.79-a-unit product's breakeven), at 100% (section 2d, decision 157; 85% from Oct 26 to Oct 28); a product prior may be used when the query benchmark is missing, but IDX remains unknown | Economic starting point, not a guarantee of visibility; delivery is reviewed separately |
| **Discovery** | Broad / phrase / auto keywords | The **suggested mid** in its launch test (0–1 orders) and with 2+ orders at a keyword index of 0.8 or more (section 2i, decisions 177 and 178). Otherwise, since 2026-10-29 (decision 162): breakeven at the click-weighted SQP price of the searches it served, uncapped (below). Before, and still for a keyword with no served search on record: breakeven (100% since decision 157, section 2d) at the keyword's own conversion, capped at the product's average breakeven click until it has 3 orders, or 2 orders at a keyword index of 1.1 or more against the product's ad conversion (`discovery.cap_lift_orders`, `cap_lift_index`; Kim 2026-10-21; 1.25 until decision 178) | Finds new searches |
| **Negate** | Irrelevant to the product (relevance lists + the negative audit) | Paused / negative | Via the negative-audit approval table |
| **Leave** | Small, no data | profit × 10% | — |

**Product size check, 2026-10-24 SGT:** Read the product file's `size`, falling back to the negative-audit
fingerprint's `size`. Dimension pairs are order-free (6x4 = 4x6), including spaces, inch units and decimals.
A search naming any other size is a relevance mismatch even with orders or a generic protect phrase: never
promote, invest, protect/whitelist or use it as a harvest seed. Hold its change rows (raises, promotions, new
campaigns, budgets and unverified pauses) with a reason naming the sizes; bid cuts keep their normal lane.
**Kim, October24: a confirmed wrong-size positive-keyword relevance pause also follows its normal lane and
applies through Auto when eligible.** Verify actual dimensions against the fresh live listing, including all
alternate/folded sizes; save the raw read and `listing_size_verification.json` as [live-size-pauses.md](live-size-pauses.md)
requires. The planner and apply preflight check that evidence. A fingerprint alone remains insufficient (the
notebooks' 8.5x11 is approximate, decision61). Ambiguous/conflicting sizes, explicit size protections, human
decisions, ownership, data freshness, shadow/readiness and other independent guards remain unchanged. This
exception releases only the size hold on an identified relevance pause, never routing/replacement changes.
Negatives still need the negative audit. No-size searches and matching sizes keep their existing rules.
A protect entry that itself names a size (Get Well's `5x7`, whose 5x7 searches convert; logs/2026-10-23) is a
decision: that size counts as allowed for the product. A generic protect phrase ("thank you") is not.
When the product size is unknown, keep existing behavior and say so once in the plan summary.

**The Hold uplift test** (Kim, 2026-10-23, decision 108: "Let's lock this +15% bids for idx 1 to 1.1"). Hold searches
get under 1% of their search's impressions at breakeven (latest plans, 2026-10-23), and one at index 1.0–1.1 converts at or
above the market. So a consumer exact keyword of a Hold search whose trusted index is 1.0 or more (and under 1.1, where
Hold ends) bids its breakeven +15% (`config.json` `hold_uplift`); 0.8–1.0 stays at breakeven and is the comparison group.
The row carries `hold_uplift: 15` and says so in its why; the raise to it is the role's price, so Auto. The first applied
run of a product records the baseline (`scripts/hold_uplift.py baseline`), which puts the dated review (2026-11-20) on the
product's page; the review keeps the uplift or sets `hold_uplift.enabled` false by
docs/experiments/hold-uplift-2026-10-23/protocol.md. **Ended early on 2026-10-25** (Kim, decision 135: "#10 - alright
then" on fix 10 of the AI spend review, bid at or below breakeven): `hold_uplift.enabled` is false, so every Hold keyword
bids its breakeven again; the experiment folder keeps the baselines.

**When Amazon gives no suggested bid** (Kim, 2026-10-23, decision 106: "fall back to soldscope suggested bids if
they are not available ... if soldscope is also not available, then we can fall back to any other method to determine the
bid first"). A missing suggestion never stops a run:
1. Amazon's suggestion comes first: `plan.py` exits 2 and lists the searches in `need_suggested_bids.json`.
   - Read them with MarketplaceAdPros (data-pull.md).
   - On a rate limit, wait about 5 minutes and retry once, spacing the ad-group calls about a minute apart.
   - Then stop asking Amazon.
2. Save SoldScope's estimate for each search still missing in `soldscope_bids.json`.
   - The estimate is `cpcMin`, `cpc` and `cpcMax` for that exact query.
   - A zero means SoldScope has none. A related query's figure never stands in.
3. Write `bid_sources_tried.json` with what happened, for example `{"amazon": "rate limited at 00:45 SGT after one retry",
   "soldscope": "read for 3 searches, 1 with a figure"}`, and rerun.
4. The planner (`scripts/bid_fallback.py`) prices each search still without an Amazon suggestion, in this order:
   - SoldScope's estimate, as a range: its median, or breakeven if higher, never above its high.
   - An estimate: the higher of the search's own 90-day ad cost per click (10+ clicks) and the median of Amazon's
     suggested medians on the product's other searches this run (3+ searches). It has no high, so the bid is the estimate,
     or breakeven if higher.
   - Otherwise, 1.5 × breakeven, the no-suggestion bid.
5. Each priced row carries `bid_source` (`soldscope`, `estimate` or `none`) and says what it was priced on in its why.
   - `plan.json` `summary.bid_fallback` lists them, and the Slack recap names them in one line.
   - Lanes don't change: a promotion goes out on its ladder as usual.
   - An invest re-price inside SoldScope's range is automatic, as one inside Amazon's range is.
6. A business (B2B) invest search with Amazon tried takes the no-suggestion bid at its B2B breakeven, because a consumer
   or SoldScope figure never prices a B2B auction (rulebook 9.7).

Keyword-level conversion is the keyword's own record shrunk toward its search's conversion (exact match) or the
product's ad conversion (broad/phrase/auto), with the same 10-click prior.

**Pricing on each search's own SQP conversion (Kim, 2026-10-29, decision 162; config.json `pricing.search_conversion`
"sqp").** The paragraph above is the rule before ("ad"). Now:
- **A search's price** is its SQP conversion: all our clicks on the listing for that search, ads and organic, shrunk toward
  the search's market with the 10-click prior, `(our purchases + 10 x market) / (our clicks + 10)`, whenever SQP shows any of
  our clicks. A search with none is priced on the ad report, as before. Its breakeven click is `profit per unit x price`,
  with profit per unit at the settled referral fee (decision 136), read from the settlement report on every run (decision 169). The search's role and index (section 1) are unchanged.
- **An exact keyword** bids its search's price through its role: Hold, Defend and Test at the non-rank factor, Trim at 70%,
  Invest and Prove first at Amazon's suggested median or breakeven if higher. Its own ad record no longer pulls the price
  toward its ad conversion.
- **A broad, phrase or auto keyword** bids the click-weighted price of the searches it served in the 90-day search-term
  report (each search at its own price), with no product-average cap, once it has served 10 or more clicks
  (`thresholds.trusted_min_clicks`, added with decision 165: with no +25% step, one click on a thin search would set the
  bid). Under 10 served clicks it keeps the rule before.
- **Sponsored Brands keywords** are priced the same way, times the SB/SP conversion ratio.
- **Unchanged:** product targets and SD (no SQP of their own), B2B (its own record), the roles, the evidence
  ladder, the leak check (the efficiency guard until 2026-10-31) and stop-loss.
- **Known limit, shown to Kim before the go:** SQP blends organic clicks, which can convert above ad clicks. On Oct 29
  data, gel pens ads converted at 0.36 of SQP and highlighters at 0.85. The weekly leak check (section 2g, decision 175; the
  efficiency guard until 2026-10-31) is the brake where ordinary keywords' ads lag.

**Shopper kinds (2026-10-21, section 9).** Every campaign is one of three kinds, and its kind decides who prices it:

| Kind | How the planner recognises it | Who prices it (built 2026-10-21) |
|---|---|---|
| **Consumer** | Every campaign that is neither of the two below | The roles above |
| **Business** | Amazon-Business-exclusive: the live campaign read carries `siteRestrictions: AMAZON_BUSINESS`, or the name holds a `b2b_campaign_markers` entry (`B2B`). The marker catches a campaign whose record isn't in hand: a search-term row carries only the name, and a campaign read may come without the flag | The roles above, every one of them (Invest and Rank included), on the B2B keyword's own evidence, inside the team's B2B campaigns, in the same lanes as consumer rows (section 9; Kim, 2026-10-21 evening) |
| **Audience** | The name holds an `audience_campaign_markers` entry (`AMC`, `Low Bids`, `Low 0.`) | Capped at the keyword's (or target's) breakeven click and never raised, never paused for clicks (since 2026-10-25, decision 135: these went from about $10 to $45 a day once their hours opened at handover). Until then left as they were |

Business wins over audience: a B2B campaign with "Low Bids" in its name is a different shopper, not a cheaper copy.

## 2a. Delivery-aware validation (added 2026-10-19 SGT)

Every run adds the review in [visibility.md](visibility.md). The role calculation remains the economic baseline;
Amazon's suggested low/median/high is auction context, not a universal floor or a guarantee of impressions.
Keep bid, effective placement/dynamic bid and actual paid CPC distinct.

- **Already receiving enough qualified traffic:** keep the economic approach; do not raise a bid merely to match
  Amazon's suggested low. Judge progress toward a product/query-specific evidence goal, not a universal impression
  or click threshold.
- **Test:** after seven verified eligible days, insufficient delivery can justify a separately reviewed, bounded
  visibility test. The default proposal lasts 14 days, with concrete bid, spend and net-loss limits supplied and
  approved per target. The existing $0.35 baseline is not Amazon's live suggested low and can exceed breakeven.
- **Discovery:** preserve the broad/phrase/auto economics; isolate a promising shopper query for exact validation
  instead of blindly raising every search matched by the broad target.
- **Hold / Defend:** review meaningful lost coverage and economics before proposing recovery. Good organic coverage
  or low demand is not a reason to buy extra impressions. A beyond-economics recovery needs a reviewed allowance.
- **Trim:** reduced delivery can be intentional. Never apply a suggested-low rescue floor to a sufficiently
  evidenced poor converter. Retesting requires new evidence or a meaningful offer, relevance or seasonal change.
- **Invest / Prove first:** preserve the approved experiment, placements, loss allowance and original review clock.
  A delivery diagnostic is not permission to cancel it, increase its allowance or restart its clock.

Check eligibility, inventory/offer, budgets, schedules, negatives, ownership and query demand before calling a bid
too low. High impressions with low CTR, enough clicks with weak CVR and low demand are different problems. Missing
inputs produce a data request/hold, not an invented diagnosis. The report and trial proposals are not executable
payloads, a scheduler, or a worker; no new live change or loss allowance follows from generating them.

## 2b. Product targets (added 2026-10-19, Kim's request)

Sponsored Products ASIN and category targets. Until this date they were priced only by Scale Insights' 202 Brake
and imported by strategy 121 at $0.37–0.63, often above twice the product's breakeven click.

**What a target is judged against.** SQP covers search queries, not targets, so there is no market conversion for
a target. A target is judged against the product's own ad conversion (`asin_ad_cvr`), with the same 10-click prior as
keywords: `cvr = (orders + 10 × product ad cvr) / (clicks + 10)`. Its breakeven click is profit per unit × that
conversion. Its index is that conversion ÷ the product's ad conversion.

| Role | Which targets | Bid |
|---|---|---|
| **Pause** | 22+ clicks and no order (90 days; `targets.pause_min_clicks`, Kim 2026-10-19). About 92% sure such a target converts under 0.8x the product's average | Paused |
| **Trim** | 15+ clicks and index below 0.8 | 70% of its breakeven click (min $0.10) |
| **Hold** | 3+ orders (`targets.proven_orders`) | Its breakeven click |
| **Test** | Everything else | Breakeven at its own conversion, capped at the product's average breakeven click until it has 3 orders |

- **Left alone:**
  - targets in campaigns whose name carries a placement experiment (`targets.skip_campaign_markers`, e.g.
    "Single Product Targeting - TOS 900%"). A breakeven bid there would be multiplied by the boost, so those
    campaigns stay a decision;
  - targets in business campaigns (section 9);
  - a target with no bid of its own (it bids its ad group's default) or a paused one, counted on the run summary.
- **Audience campaigns** (since 2026-10-25, decision 135): a target there is capped at its breakeven click, never
  raised and never paused for clicks.
- **Auto-targeting groups** (close match, loose match, substitutes, complements) are priced the same way since 2026-10-25
  (`targets.auto_targets`, decision 135: "we should also cap the auto, SD and idle keywords campaigns").
- **Sponsored Display targets** are priced the same way since 2026-10-25 (`targets.sd`, decision 135), in enabled CPC
  campaigns only: a vCPM campaign's bid is per thousand impressions (`targets.sd_skip_cost_types`). A display click converts
  differently from a search click, so an SD target is judged against the product's own display conversion: its SD targets'
  pooled orders and clicks, shrunk toward the product's ad conversion by the 10-click prior. Scale Insights reports them
  (`get_target_performance` ad_type SD) and MarketplaceAdPros gives each campaign's state and cost type (data-pull.md).
- **Sponsored Brands product and category targets** are priced too since 2026-10-27 (decision 155; `sb_targets_p*.json`),
  at breakeven × the non-rank share, cut only, never raised; SB theme targets the same since decision 156. Section 5b.
- **No invest role.** A product target doesn't build organic rank on a search, so it never bids above breakeven.
- **Scale Insights' 121 import** adds new ASIN targets that sold between weekly runs. Each one is priced at the next
  weekly run.
  - **Capped at $0.35 since 2026-10-19 (Kim).** Strategy 121 uses import rule 21053, "205 Import ASINs with orders
    - max $0.35 (AI products)": a copy of the shared rule 10200 with its maximum bid lowered from $0.67. A new
    import can no longer sit at twice breakeven for a week.
  - Rule 10200 is unchanged for the 759 ad groups of products still on Scale Insights rules.
  - Scale Insights' own 121 negative rule ("[ASIN] Negate ASINs without Orders (10 clicks)") still negates ASINs with 10
    clicks and no order. So the 22-click pause above mostly catches category targets, and ASIN targets the rule doesn't
    reach.
- **Payloads:** `9_target_pauses.json` and `9_target_bids_NN.json` (`sp_targets` updates), and since 2026-10-25
  `9b_sd_target_updates_NN.json` (`sd_targets` updates: a numeric `targetId`, a lowercase state), applied after the keyword
  bids.

## 2c. Every keyword and target is priced (Kim, 2026-10-25, decision 135)

Kim: "we'll price every single keywords now, leaving none behind with the best data available". The AI spend review
(2026-10-25) found keywords and targets the planner never priced: they had no 90-day row in Scale Insights (most had run an
hour a day on a "5–6am only" schedule), so they kept their old Scale Insights bids, and once onboarding opened their hours
they spent at them (one bid $1.11 against a $0.39 breakeven).

- **The live read.** Each run reads the product's live Sponsored Products keywords and targets from MarketplaceAdPros
  (`live_keywords_p*.json`, `live_targets_p*.json`) and its Sponsored Display targets (data-pull.md, "Live inventory").
  A live keyword or target with no 90-day row joins the plan with no clicks; a reported one takes its live bid; a paused
  one (or one of a paused campaign or ad group) is priced cut only and left paused since decision 155
  (`inventory.paused`), so turning it back on can't bring back an old bid. `plan.py` stops and writes `need_live_inventory.json` when a read is missing
  (`inventory.required`), unless the run is planned with `--partial-inventory "<why>"`, which the run summary records.
- **The best data it has.** A keyword is priced by its role from its own clicks and orders, shrunk toward its search's
  conversion (exact) or the product's ad conversion (broad, phrase), as before. With no clicks of its own, that is its
  search's conversion or the product's.
- **Raised without clicks of its own since decision 168** (decision 168, Kim, 2026-10-29, "the full package"): `inventory.no_data_raise` is true, so a keyword or
  target with no clicks of its own goes to its price like any other (a keyword's search SQP conversion, decision 162; a
  target's product conversion). Until then it was never raised above its live bid on that run (it kept the 12 highlighter
  targets at $0.38 on Oct 29). `false` brings the rule back; a seasonal product in season is exempt either way.
- **Auto, Sponsored Display and audience campaigns** are priced too (2b, and section 2's Audience row).
- **Older Sponsored Brands campaigns** are priced at the Sponsored Brands conversion, cut only (5b).
- **The run summary** (`summary.inventory`) says what the live reads added, refreshed and left out, and why.

**Consolidate before adding** (fix 7 of the review, "yes ok correct"). When a search gets its own exact campaign or
Sponsored Brands video this run, each older copy of it keeps its pause row (a Sponsored Products copy goes with its
promotion's bundle; a Sponsored Brands copy is paused only from the run after, once the AI's video owns the search, so
the search never goes dark while the video is held or in Amazon's moderation, 2026-10-26) and also drops the same day to
a holding bid: profit per unit × `inventory.copy_holding_bid_cvr` (10%), never under the ad type's
minimum, only when its live bid is higher. The row carries `copy_hold`; it shares its promotion's lane (a Sponsored
Products copy is in the promotion's bundle; a Sponsored Brands copy's holding bid follows its search's held promotion,
and its held new video), is never a
stop-loss cut of an invested search, and is not stepped down by the big-cut rule (7.3), since the search's orders move to the
new owner.

## 2d. Non-rank bids at 100% of breakeven (decision 157, 2026-10-28; 85% from 2026-10-26, decision 139)

**Today: every non-rank keyword and target bids 100% of its breakeven click** (`thresholds.non_rank_bid_factor` 1.0), less
only where a brake in section 2g applies. The 85% below is history: if a row, a log or an older note says 85%, it is from
Oct 26 to Oct 28.

**Changed 2026-10-28 SGT (Kim, decision 157): non-rank bids are back at 100% of breakeven** (`non_rank_bid_factor` 1).
Kim, project thread, 2026-10-28: "#4 #5 implement", where #4 was "non-rank bids at 100% of breakeven instead of 85%". Why:
spend on the low-margin AI products fell too far (the gel pens' breakeven click is about $0.18, so 85% of it served almost
nothing). Since 2026-10-31 (decision 175) only the top-10 rule (75%) and Trim (70%) bid an ordinary keyword under
breakeven: the organic-share brake and the efficiency guard's step-down are gone (section 2g). The rest of this section is
the decision 139 record.

Kim, 2026-10-26 about 00:28 SGT: "perhaps instead we should look to consider investing for rank for the keywords with
>1.1 idx, and bid more conservatively for the rest of the keywords on a keyword bid level rather than lowering campaigns
budget". On the card he chose "85% of breakeven".

- Every keyword and target that is not a rank search bids **85% of its breakeven click** (`thresholds.non_rank_bid_factor`,
  0.85): Hold, Defend, Test (after its floor), Discovery (after its cap), the audience cap, product, auto and Sponsored
  Display targets (Hold and Test), Sponsored Brands keywords (Hold, Discovery, Test) and business keywords (`business.price`).
- Unchanged: Invest and Prove-first bids (and a rank search's Sponsored Brands keyword at `sb_rank_ratio`), Trim (70%), the
  low Leave bid, the copy holding bid and the harvest default bid.
- Why: breakeven aims for zero profit on each click, and the conversion it is priced on runs high (SQP counts organic
  clicks). 85% leaves a margin without starving the keywords. Rank searches keep bidding to be visible.
- A seasonal product **in season** keeps breakeven bids (docs/seasonal-bidding.md): `nr` is 1 while a season phase runs.
- The share was on the rows' why ("Not a rank search, so it bids 85% of breakeven (decision 139)") and in their action
  ("Hold at 85% of breakeven"). Setting the factor to 1 turned it off, which decision 157 did on 2026-10-28.

## 2e. The product-page base bid and down-only bidding (Kim, 2026-10-26, decision 140)

Kim, 2026-10-26 about 00:29 SGT: "it sounds good. let's try this to build 1 and 2 as you suggest". The leak: on Oct 18–24,
2026 (US), product pages took about $3,950 of the $10,600 Sponsored Products spend on the AI products, converting 8.4%
against 15.1% at the top of search, at 91% ACOS. A keyword has one bid for every placement, priced on its blended
conversion, so it overpays on product pages and Amazon lets a placement go up, never down.

**The product-page base bid** (`scripts/placement_shape.py`, `placement.shape`; [placements.md](placements.md), "Product-page
base bid"). In a campaign with enough placement data (50 clicks and 5 orders in the mature 90-day window of
`placement_inputs.json`), each placement's conversion is shrunk toward the campaign's own by 30 clicks. The placement that
converts best keeps the keyword's bid as the plan priced it; each other placement bids its conversion against that best one
(never under 50% of it); a rank campaign's top of search keeps its full policy bid (+50% Invest, +30% Prove first). The base
bid drops to the lowest placement's share and whole-percent modifiers, rounded down, raise the others back, so **no
placement bids more than the plan priced it**. Example: a $1.00 keyword converting 8% on product pages and 16% at the top of
search gets a $0.50 base and +100% top of search: $1.00 at the top, $0.50 on product pages.
- It runs after the lanes, only on an Auto product with fresh data and the live keywords and targets read, and only on a
  campaign the product has alone (live product ads), not global, audience, Amazon Business, harvest or a "TOS 900%"
  experiment, with no budget, top-of-search or other campaign row this run, with every row in the Auto lane or held by
  the planner (Monitor, no person's decision; since 2026-10-26 a held row's keyword is shaped from its live bid) and every
  serving bid known (none on an ad group's default bid, none kept by a review). A shape that cuts no placement by 10% is
  not written. `summary.placement_shape` lists what it shaped and why it left a campaign alone.
- Each serving bid of a shaped campaign is written at its shaped base (`shape_base`); a bid the plan keeps gets a row of
  its own ("Price unchanged", `shape_only`). The campaign's 'Placement shape' row writes `9c_placement_shape.json`, last:
  only once every shaped bid of the campaign is written and read back (map-playbook.md, "Product-page base bid").
- It replaces the placement-economics rule "do not manufacture a boost because the placement converts better" for the
  campaigns it shapes: the modifiers it writes are a re-split of the plan's own price, never a raise over it.

**Down-only bidding** (`placement.down_only`). Every live Sponsored Products campaign on up-and-down bidding gets a
'Bidding strategy' row to down only (`5b_bidding_strategy.json`): MAP's optimizations shape, every live placement and
audience adjustment sent back as read. Up and down lets Amazon raise a bid up to 100% at the top of search and 50%
elsewhere; down only never raises it. Auto, except an audience (AMC, low-bid) campaign, which people own (decision 107), and
a campaign not shown to advertise this product alone: those wait for the book owner. A shaped campaign's own write moves
it to down only, so its strategy row is folded into the shape. Fixed bids (MANUAL) never raise a bid and are left alone.
On Oct 25, 30 of the gold notebooks' 242 live campaigns were on up and down: 21 AMC audience campaigns with +300% audience
adjustments, 8 low-bid and 1 auto.

## 2f. The brand is organic only (Kim, 2026-10-20; the planner's guard since 2026-10-26, decision 141)

- **A brand search** is any search that holds a word of `config.json` `scale_insights.blacklist_keep` ("yourbrand"), close
  variants applied: "yourbrand birthday cards" as much as "yourbrand". Kim, 2026-10-20: "YourBrand as the brand should be
  left to organic"; the brand stays on every product's phrase blacklist.
- **Never invested in, held or tested at a raise.** Whatever the ladder, a retained Prove first or a season says, a brand
  search's record (consumer and business) becomes Leave, cut only (`plan.py` section 1c', `demote_brand`): no exact
  campaign, no Sponsored Brands video, no budget or top of search, no funnel negatives, no invest log entry.
- **Its live keywords are cut, never raised:** Sponsored Products (any match type) and Sponsored Brands.
- **The blacklist rescue never frees or whitelists it** (`blacklist_rescue.brand_search`), even when it sits in an invest log.
- **The brand sweep:** before the re-rank, any row that would still create, fund, whitelist or raise a brand search is
  dropped and listed in `summary.brand_guard.dropped_rows` (with the brand searches demoted in `.searches`). A non-empty
  `dropped_rows` means a section missed the role pass: say so in the run log.
- Why it became code: the 2026-10-26 rollout run made "yourbrand birthday cards" (index 1.21, 207 searches in 12 weeks) an
  Invest search on B0SAMP0014 and took "yourbrand" off its blacklist; the exact campaign was live 09:49-10:03 SGT before it
  was reversed by hand. The Oct 25 run had raised the same rows and a person skipped them, but a skip without a lock does
  not carry to the next run.

## 2g. The 50/50 goal: the organic share, the top-10 rule and the weekly leak check (decision 143, 2026-10-26; reshaped 2026-10-31, decision 175)

Kim, 2026-10-26 about 11:00 SGT: "how can we build this while maintaining our goal of ranking and 50% organic units to
50% ppc units" (decision 143: an organic-share brake, a top-10 rule and a weekly efficiency guard). Reshaped by Kim on
2026-10-31 (decision 175), because the brake and the guard cut visibility while products are still ranking: "agreed on
number one to drop the under-half organic cut. Just let ordinary keywords stay at 100% of break-even"; "you can turn it into
a leak check"; "when we are already ranked top 10 for the keyword ... we can bid 75% of the break-even, but continue
investing in the ranking and the high-index keywords. The idea is that we have to continue spending, even if we are ranked,
because Amazon wants us to continue spending." Code: `scripts/organic_share.py`; settings: config.json `organic_share`;
inputs: `sales_daily.json` and `campaign_days.json` ([data-pull.md](data-pull.md), [budget-headroom.md](budget-headroom.md)).

**None of this touches a rank search.** Invest and Prove-first bids, rank budgets, every campaign budget and new Prove-first
launches stay as they are (decisions 99 and 174: no money cap). It steers only the ordinary keywords: the non-rank ones.

How ordinary keywords bid, by index (Kim, 2026-10-31):

| Index | Role | Bid |
|---|---|---|
| 0.8 to 1.1 (or not enough evidence) | Hold, Test, Discovery | 100% of breakeven (`non_rank_bid_factor` 1, decision 157) |
| 1.1+ but small, or already defended | Defend | 100% of breakeven |
| Under 0.8 on 15+ clicks | Trim | 70% of its own breakeven (`trim_factor`), pause under 0.5 on 30+ clicks: unchanged. Its breakeven is already priced on its own weaker conversion, so 70% is a second discount, and these searches trail the market, so they are not ranking candidates |
| Any, on a search we already rank top 10 for organically | the top-10 rule | 75% of breakeven (`top10_factor`) |

- **The organic share** of sales over the last 28 days (`share_days`) is reported against 50% (`target_share`) in the run
  summary. It moves no bid. Until 2026-10-31 a mature product under 50% bid its non-rank keywords at 70% of breakeven (the
  organic-share brake, `brake_factor`, removed). What grows organic share is the rank searches, judged by the stop-loss
  (section 4) on organic rank and organic purchases.
- **The top-10 rule.** A non-rank keyword on a search the product already ranks for in the top 10 organically bids **75%
  of breakeven** (`top10_factor`; 70% from Oct 26 to Oct 31) whatever the product's share. "In the top 10": the search's
  Rank Radar median over its last 14 days of readings is 10 or better (`top10_rank`, `top10_days`; one good day is noise: 3 of
  the gel pens' 30 searches touched the top 10 on single days, 2026-10-21). A search with no Rank Radar counts when at least
  half its SQP purchases are organic (`thresholds.defend_organic_share`) and it has 3+ organic purchases
  (`top10_sqp_min_purchases`). It applies to Sponsored Products Hold, Defend, Test, Discovery and the audience cap, and
  Sponsored Brands Hold and Discovery; never to a rank search (an Invest or Prove-first search keeps investing in the top
  10) and never to a business (B2B) keyword. The searches are in `summary.organic.top10`, and the row's why names the rule.
- **The weekly leak check** (replaced the efficiency guard). Ordinary keywords bid breakeven, so together they should not
  lose money. The check reads the product's **ordinary** campaigns, Sponsored Products (`campaign_days.json`) and
  Sponsored Brands (`sb_campaign_days.json`, the product's own SB campaigns by id; Kim, 2026-10-31: "extends to sponsored
  brands as well"): every campaign that is not a rank campaign (the plan's Invest and Prove-first exact campaigns, the AI's SB
  video series and any SB campaign holding an invest search's live exact keyword), not B2B and not a multi-product
  collection, over the last 7 settled days (`leak_days`; the newest 2 days, budget_headroom `settle_days`, are left out while attribution
  fills them): profit = orders × profit per unit − spend, SP and SB together (`leak.channels` splits them). When that loses
  more than $10 (`leak_tolerance`), the run plans again and pauses the ordinary SP and SB keywords (Hold, Defend, Test,
  Discovery; not audience, business or a rank campaign's) with 15+ clicks (`leak_pause_clicks`) and no orders over 90 days,
  except a keyword still in its launch test (2i, decision 178: testing or extended), and says so in the Slack message (`notify.py`). There is **no bid
  step-down and no hold on new Prove-first launches** (both were the efficiency guard's, Oct 26 to Oct 31), and it never
  touches a rank campaign, a budget or a rank bid. A missing `campaign_days.json` or `sb_campaign_days.json` leaves that
  channel out, and the summary's `note` says so; it never stops the run.
- **Rank Radar on every invest search.** `summary.organic.radar_missing` lists the invest searches with no radar; the run
  adds them within the DataDive quota (decision 105; [data-pull.md](data-pull.md)), so the top-10 rule and the stop-loss
  (section 4) can read them.
- **The record.** `summary.organic`: the share and its window, `non_rank_factor` (what this run used) against
  `base_factor` (the non-rank share: 100% since decision 157), `top10`, `leak` (profit, spend, orders, line, `tripped`,
  `acted`, `paused`, `sb_paused`, `channels`, its window and campaign count), `radar_missing`, and a `note` when
  `sales_daily.json`, `campaign_days.json` or `sb_campaign_days.json` was missing. Setting `organic_share.enabled` to false turns all of it off.

## 2h. Every campaign, keyword, target and setting has one owner (Kim, 2026-10-27, decision 155)

Kim, 2026-10-27, after the Oct 26 spend spike on old launch, TOS 900%, Sponsored Brands and B2B campaigns: "every single
campaign and every single keyword falls under the purview of the skill as it runs its process. Of course, the existing TOS
rules and all that must be treated as well, so that the planner doesn't get confused." He chose "Build 0 to 9, placement
table included" on the decision card. What each part does:

1. **Placement policy** (`config.json` → `placement.policy`; references/placements.md, "Placement policy"). A campaign that
   is not a rank campaign goes to 0% top of search on its own, enabled or paused, the "TOS 900%" placement experiments
   included (they end here). A rank campaign (the exact SKC of an invest search, a retained or season rank search, a B2B
   invest owner) keeps the invest policy (+50% Invest, +30% Prove first). Where the boost can't come off this run (settings
   not read, a global campaign, still on up-and-down bidding, audience adjustments), every non-rank bid of the campaign is
   priced at price / (1 + boost), so a top-of-search click never costs more than the price. The overnight copies (`ON80 |`, and
   `ON50 |` since round 2) and the experiments named in `placement.shape` are left alone; since 2026-11-04 every row on a
   copy (bids, budgets, pauses) is held too (`experiment_hold`, payloads/held/), since the test's own thread sets them. A shaped campaign (2e, decision 140) is not an exception to this: the shape starts from 0%, lowers the base to the worst placement's share and raises the better ones back, top of search included, so a non-rank campaign can end with a top-of-search modifier (+28% on the 50-pack, 2026-10-31) while no placement bids more than its price. That is the planner's own Auto row (`9c_placement_shape.json`, written last); it needs no one's approval. (Clarified 2026-10-31 after Codex asked: this is how the code has worked since decision 140.)
2. **Audience copies move to down-only bidding on their own** (`placement.down_only.audience_auto`). Down only can only
   lower a bid, so it no longer waits for a person (decision 107 kept AMC with people).
3. **Sponsored Brands** (`sb_video`): older SB campaigns with Amazon's bid optimisation on get it switched off ("SB bid
   optimisation", Auto), their positive placement modifiers set to 0% in the same write; SB product and category targets
   are priced (cut only); audience and B2B SB copies are capped at their breakeven x the non-rank share, never raised;
   paused SB keywords and targets are priced cut only.
4. **Dormant audience and B2B keywords** that spent in the last two days with no 90-day row are capped the same way.
5. **Ad-group default bids** (`inventory.ad_group_default_bids`, `live_ad_groups_p*.json`): priced like a Discovery
   keyword (the B2B pool's conversion in a B2B campaign), cut only. Keywords and targets without a bid of their own bid
   it, and Scale Insights' import rules add new keywords at it. The harvest ad group keeps its own starting bid; rank
   campaigns and placement experiments are left alone.
6. **Paused keywords, targets and campaigns** (`inventory.paused`, `targets.paused`, `sb_video.paused`): priced by their
   role and written as a cut only, marked `paused`; they stay paused, so turning one back on can't bring back an old
   launch bid. A paused copy of a rank search still never holds the search (decision 154).
7. **Multi-product campaigns** the product file lists in `shared_campaigns` (`[{campaign_id, products, profit_per_unit_min}]`,
   read as `shared_campaigns.json`) join the product's campaigns. Their bid rows are priced at the lowest profit among the AI
   products they advertise and kept only as cuts; the placement policy and down-only bidding apply; anything else (a
   budget, a pause, a new keyword) is left to a person. One shared with a non-AI product stays Scale Insights'
   (`ownership_scope`, decisions 109 and 111).
8. **A morning check for hand changes in Scale Insights** (`scripts/si_changes.py`): a person's bid, import, budget,
   placement, status or dayparting change on an AI product is a second bid owner (rule 2). The routine flags it in its Slack
   message and runs that product today. People make no manual Scale Insights bid imports on AI products
   (docs/sweep-playbook.md).
9. **Dayparting** stays as it is: rule 203's moves are expected and recognised (decisions 150 to 152).
0. **The coverage ledger** (`scripts/coverage.py`, `config.json` → `coverage`): after the plan, every live campaign,
   keyword, target and ad group (SP and SB) gets one status (changed, priced, rank, policy, boost_kept, at_policy,
   experiment, ad_group_default, paused_kept, si_owned, harvest, or unowned). `coverage.json` lists them and
   `summary.coverage` counts them. An **unowned** one (read, live, and no rule handled it) stops the run, "Nothing
   planned", unless `--accept-unowned "<why>"`, which the summary keeps. `reads_missing` names the live reads the run didn't
   have; with `coverage.stop_on_missing_reads` it stops too, and `--accept-unowned` lifts that.
   **Required reads (decision 191, Kim 2026-11-05: "make sure we are optimizing both sponsored products and sponsored
   brands at the same time").** A read in `coverage.required_reads` (`sb_campaigns`, `sb_keywords`, `sb_targets`,
   `sb_themes`, `live_ad_groups`) that is missing stops the plan with exit 2 and nothing planned, and no flag lifts it
   (`coverage.required_missing`). So a run never applies its Sponsored Products bids while its Sponsored Brands keyword
   bids or ad-group default bids wait for another day. The B0SAMP0007 run of 2026-11-05 planned past the SB read with
   `--accept-unowned` and sent 847 SP bids with no SB bid; replayed with the SB keywords read, the same plan carried 59
   SB bid changes (58 cuts) and an SB video campaign.

One owner per search (section 3, below) is unchanged: a search on several campaigns is still priced in each by its role.
Choosing one owner per search across all of a product's campaigns is designed first, not built.

**Decision 156 (Kim, 2026-10-27): every campaign the product's own ads serve in, and every target type.** Kim: "check
to see if the new skill covers every single campaign and every single keyword, product targeting on SP, SB, SD for the
ASIN, don't leave any out". What it added:

- **Campaigns are found by their product ads** (`inventory.ad_campaigns`, `ad_campaigns_p*.json`; references/data-pull.md,
  "Campaigns by product ad"), not only by the ASIN in their name. A single-ASIN campaign named without it (the "Auto -
  $0.65/$0.30 down only" ones, $257 in the 30 days to Oct 25, 2026) is priced like any other.
- **Multi-ASIN campaigns are left out on purpose** (Kim: "we can leave out campaigns with multiple ASINs in the
  campaigns, because these are done on purpose for product collection ads and cross selling campaigns"): an SP or SD
  campaign whose ads advertise several ASINs, and an SB campaign named "Product Collection" or "Store Spotlight"
  (`sb_video.multi_asin_markers`). They are never priced, even when their name carries the ASIN, and the ledger lists them
  (`multi_asin`). The section 7 pricing of `shared_campaigns` is switched off (`inventory.shared_campaigns` false).
- **Audience boosts are priced around** (`placement.audience`; references/placements.md, "The audience boost"): a non-rank
  bid in a campaign with an audience bid adjustment is price / ((1 + kept top of search) x (1 + audience boost)).
- **Sponsored Brands theme targets** are priced, cut only (`sb_video.themes`, `sb_themes_p*.json`, `8d_sb_theme_updates.json`).
- **Sponsored Display**: a live target with no 90-day row (`live_sd_targets_p*.json`) is priced, capped and never raised;
  a vCPM campaign is listed for a person (`vcpm`), never priced like a click.
- **The ledger** also covers SD campaigns and targets, SB themes, each SP campaign's bidding strategy (up-and-down with no
  row moving it is unowned), and checks that what it calls priced was priced (`_priced`). New statuses: `multi_asin`,
  `vcpm`, `down_only`.
- **A missing read stops the run** (`coverage.stop_on_missing_reads`): until then it only warned, so a run without
  `live_ad_groups` could not see an ad group's default bid. Plan again once the read is saved, or with
  `--partial-inventory "<why>"`.

## 2i. The suggested mid for validated and launching keywords (Kim, 2026-10-31, decision 177)

**Since 2026-11-04 (decision 183) the mid prices Sponsored Products exact keywords only** (`mid_bid.match_types`
["exact"], `mid_bid.sponsored_brands` false). Broad and phrase keywords and Sponsored Brands keywords keep their role's
price (breakeven, Trim 70%, top 10 75%). Kim's visibility test that morning (10 cheap top-spending products, then SB
and B0SAMP0006) showed the mid ($0.80 to $2.10) far above what a click is worth on $5.99 to $9.99 products ($0.12 to
$0.40): broad and phrase at the mid lost money (Nov 1 to 2: $452, CVR 7.7%, −$321) while exact at the mid converted at
12.9%. He kept exact at the mid for visibility ("we won't have visibility" at breakeven everywhere) and made the test the
rule so every product could go back on Auto. The text below describes decision 177 for all match types; read it for
exact keywords.

Kim: "stop cutting validated or still-launching keywords to breakeven just because they convert at about the market rate.
Bid them at the suggested middle bid so they keep real visibility." And on the source: "take the Amazon mid suggested bid
by default. If it is rate-limited or unavailable, then take Soldscope. If both are not available, then derive it using the
next best possible calculation that is close to it." Built in `scripts/mid_bid.py` and `plan.py`; config.json `mid_bid`
and `launch.test_orders`, `extend_orders`, `min_clicks`, `max_clicks`.

**The launch test is sized to the product's conversion** (Kim, 2026-10-31, decision 178: "I just want a good system
whereby good keywords don't fall through, and we can also spend appropriately to let launch keywords prove themselves").
A fixed 15 clicks gave a keyword on a 5%-converting product less than one expected order before it was judged, so the test
now ends at **2 expected orders** at the product's ad conversion (`ASIN_AD_CVR`, consumer search-term orders ÷ clicks):
clicks = 2 ÷ conversion, at least 15 (`launch.min_clicks`) and at most 60 (`launch.max_clicks`). With 1 order it is
extended to **3 expected orders** (`launch.extend_orders`), at most 90 clicks (1.5 × `max_clicks`). At 10% that is 20 and
30 clicks; at 5%, 40 and 60; at 2%, the 60 and 90 caps. Before decision 178 (the morning of 2026-10-31) it was a fixed 15
clicks with 0 orders, and 20 + 10 with 1. A keyword in its test (testing or extended) is **not paused by the leak check**
(2g) until the test ends: the test is the budget it was given.

**Which keywords bid the mid** (ordinary, non-rank Sponsored Products and Sponsored Brands keywords; `mid_bid.state`):

| State | Which | Bid |
|---|---|---|
| **validated** | A Hold keyword whose search has 2+ orders (`mid_bid.validated_orders`, counted as max(SQP purchases, ad orders), as the ladder counts them, `lanes._ladder_orders`). A Test or Discovery keyword with 2+ orders at index 0.8 or more (a Test keyword reads its search's index; a broad or phrase keyword its own conversion, with the 10-click prior, against the product's ad conversion, as the Discovery cap lift reads it). A Test search at 1.1+ on 150+ searches is Prove first on the ladder; one with fewer searches, and a broad or phrase keyword at 1.1+, keeps the mid, so it never bids less than a weaker keyword (decision 178). An unknown index (no same-query market) is validated on its orders | The suggested mid |
| **testing** | The launch test: a Test or Discovery keyword with 0 or 1 orders of its own on fewer clicks than 2 expected orders at the product's ad conversion (15 to 60 clicks; 20 at 10%, 40 at 5%) | The suggested mid; not paused by the leak check |
| **extended** | 1 order at the end of the test: more clicks at the mid until 3 expected orders (at most 90; 30 at 10%, 60 at 5%), then judged again | The suggested mid; not paused by the leak check |
| failed | 0 orders at 2 expected orders: the test is over | Its role's own price (breakeven, Trim); the leak check (2g) may pause it |
| judged | 1 order at 3 expected orders: the test is over | Its role's own price |

The bid is **the mid itself**, above or below breakeven, never Amazon's low or high. No top-of-search boost (the placement
policy, 2h, keeps non-rank top of search at 0%) and no rank campaign of its own. On a search the product already ranks top
10 for (2g), 75% of the mid (`organic_share.top10_factor`). Bidding above breakeven during the launch test is accepted. When a
keyword is in two campaigns (same text and match), only the copy with the most clicks bids the mid (`mid_bid.owners`); the
other copies keep their role's price. A raise to the mid is Auto (7.4); the low-stock park (rule 1 in AGENTS.md) still parks
increases at 14 days of cover or less.

**2+ orders on the ladder.** A search whose role would be Test (not yet trusted) is validated at 2+ orders: index ≥ 1.1
(`auto.prove_index`, decision 178) on 150+ searches makes it Rank, Prove first (its own campaign, 7.1); under 0.8 makes it
Trim; 0.8 to under 1.1 keeps it a Test keyword at the mid.

**Where the mid comes from** (`mid_bid.pick`), in order:
1. **Amazon:** the keyword's own bid recommendation in the live keyword read, else the suggested median in
   `suggested_bids.json` (exact; `suggested_bids_match.json` for broad and phrase is read only if `mid_bid.match_types`
   lists them again, which it hasn't since decision 183). A keyword without one is listed in `need_suggested_bids.json`
   (exact searches under `searches`; its `keywords` list stays empty) and the run exits 2 until Amazon was tried
   (`bid_sources_tried.json`), as for invest searches (references/data-pull.md).
2. **SoldScope:** its middle cost per click for the search (`soldscope_bids.json`), once Amazon was tried and gave none or
   stayed rate-limited.
3. **An estimate:** the higher of the keyword's own cost per click on 10+ clicks and the median of Amazon's mids on 3+ of
   the product's other searches this run (the invest searches' estimate, `bid_fallback`); with neither, the same two on any
   clicks or any one search.
4. None of these: no mid, and the keyword keeps its role's price.

A Sponsored Brands keyword in the AI's own video campaigns takes the same states on its own SB clicks and orders, and bids its
search's Sponsored Products mid × `sb_video.sb_rank_ratio` (1.0 today), the share a rank search's SB bid uses: Amazon gives no
Sponsored Brands suggestions. Older and paused SB campaigns stay cut only.

**Not covered:** rank searches (Invest, Prove first), Defend, Trim, Audience (AMC, low-bid) copies, B2B keywords, brand
searches, paused or not-live keywords, wrong-size searches, and a seasonal product in season (breakeven, section 8).
Unchanged: Invest, Prove first, Trim, the audience copies, the B2B lanes, the low-stock park, the stop-loss, the 56-day
cool-off and the leak check.

**What the run reports:** each changed row's why names the state and the mid's source; `summary.mid_bid` lists every keyword
at the mid (`rows`: channel, keyword, state, 90-day clicks, orders and spend, mid, source), the launch tests that ended this
run (`ended`), the copies left at their role's price, counts by state and source, and the 90-day spend of the launch tests
(`launch_test_spend90`), the ended tests and the validated keywords. `mid_bid.enabled` false restores the role prices.

## 3. One owner per invest search

- An invest search keeps exactly one exact keyword: its own exact SKC campaign.
- Exact copies of it elsewhere are paused ("Pause here: the exact SKC owns this search").
- Exact keywords of it in non-SKC campaigns move into a new SKC, and the old keyword is paused.
- **A B2B keyword is never a duplicate of a consumer one** (Kim, 2026-10-21), in Sponsored Products or in Sponsored
  Brands video. Owners are per shopper kind (section 9): the SKC owns the search for consumers, the B2B-exclusive
  campaign owns it for business buyers.
  - So a B2B keyword is never paused as the SKC's duplicate and never moved into a consumer SKC.
  - **Inside the business kind, one owner: the enabled B2B exact keyword with the most clicks** (90 days; ties to the
    lower campaign id). Its other B2B exact keywords of the search are paused as its copies while it invests, and the
    other B2B ad groups that paid for the search get the funnel negative (section 9.3; built 2026-10-21).
  - Why: a B2B campaign bids only in business buyers' auctions, at what their conversion pays (34.6% over the 90 days
    pulled 2026-10-21). Pausing it as a copy leaves those auctions to a consumer bid priced for a 15% converter.
  - The Oct 17–20 onboarding runs got this wrong. They paused 7 B2B exact keywords as duplicates, re-enabled
    2026-10-21 (logs/2026-10-21-b2b-repair.md). The 2026-10-18 puzzles plan also carried 13 "Videos - B2B" Sponsored
    Brands pauses for the same reason.
- **Funnel negatives:** every SP ad group that paid for the search in the last 90 days gets a negative exact for it, except:
  - the owner campaign;
  - business campaigns (a different shopper: business accounts only; a business invest gets its own negatives inside the
    B2B ad groups, section 9.3);
  - audience campaigns (a different lane: the consumer owner never negates its search there);
  - **any exact SKC where the negative is a close variant of that SKC's own keyword.** Amazon applies plurals and
    spacing variants to negatives, so it would switch that campaign off (see live-checks.md).
- **Never on the product's own blacklist** (Kim, 2026-10-21). An Invest or Prove-first search is taken off its product's
  Scale Insights blacklist: as itself, as a close variant, and as any phrase entry whose words it contains. It goes on the
  exact whitelist. Every brand search stays blacklisted (`scale_insights.blacklist_keep`; section 2f). The planner checks it when the
  run folder holds `si_blacklist.json` and proposes the edit as a "Scale Insights setup" row (scripts/blacklist_rescue.py).

## 4. Why investing above breakeven is allowed (the user's rule)

- Capping rank searches at breakeven makes a low-priced product impossible to advertise: the breakeven click sits
  below what it costs to be seen. The user's call on 2026-10-17: bid to be visible on the searches that convert
  better than the market, and bound the investment by results, not by a small dollar cap.
- **Re-rank budget:** size invest budgets from what the searches need to win about 1 in 10 of their clicks.
  `plan.py` reports this per search, as spend, orders and profit after ads.
- **The brake is the stop-loss, judged on organic results at months 3, 6, 9 and 12** (Kim, 2026-10-26, decision 142:
  "count the organic rank and organic sales only, its correct. but ranking horizon is now around 10 to 12 months on
  amazon.. not just 4-6 weeks"). An evergreen invest search is judged once at each checkpoint of investing
  (`thresholds.stop_loss_months` [3, 6, 9, 12]: day 91, 182, 274 and 365 after its `since`), on the two gains we don't
  pay for:
  - **organic rank**: the Rank Radar median of the last 7 days of readings, lower is a gain;
  - **organic purchases**: SQP purchases less every ad order of the search, higher is a gain.
  SQP impression share no longer counts: it includes the impressions we buy, so investing raises it on its own.
  - **Against what:** the reading at the last checkpoint the search passed (the invest log's `checkpoint`,
    `checkpoint_rank`, `checkpoint_organic` and `checkpoint_on`, written by `log_invest.py` when a checkpoint shows a
    gain), else its start (`rank_then`, `organic_then`). A measure that can't be read today keeps the base it was judged
    on. A search first judged late is judged at the latest checkpoint it passed; between checkpoints it isn't judged.
  - **No gain on either** steps the search down to Hold (breakeven, top of search 0%, $5/day). **Neither readable** (no
    Rank Radar for it, no SQP row or no baseline) is a 'Stop-loss review' row, held (Monitor) until a Rank Radar or SQP
    reading lets the next run judge it. After month 12 there is no further checkpoint; the role ladder still re-prices
    the search every week.
  - A seasonal rank build keeps its own weeks (section 8: 2 and 4 weeks, every run from the first, against its start),
    on the same two gains. The business stop-loss (section 9.6) keeps `thresholds.stop_loss_weeks` [4, 6].
  - Until 2026-10-26 the evergreen stop-loss judged every run from 4 weeks on (`stop_loss_weeks` [4, 6]), against the
    start, and counted SQP impression share as a gain.
  - **Since 2026-10-22 the run applies the step-down itself** (Kim, decision 98: "the AI applies stop-loss step-downs
    itself and notes them"). `plan.py` writes it (`scripts/stop_loss.py`): a 'Bid change' of the owner keyword to its
    breakeven (role Hold) and a 'Budget and top of search' row on its campaign (top of search 0%, budget min(live, $5)),
    both flagged `stop_loss_step_down` with the reason ("invested 96 days (the month 3 checkpoint) with no gain since its
    start in organic rank (40 -> 41) or organic purchases (0 -> 0)"), both Auto whatever the size of the cut. A row the plan already has on the
    keyword is marked instead, and a budget step on the campaign is dropped. A B2B search (section 9.6) steps its owner
    keyword down the same way; its campaign's top of search drops to 0% only when no other business invest is left in it,
    and its budget stays as live.
  - **A 'Stop-loss review' row for a person** is left only where no step-down can be written (the search's owner keyword
    is not in the run's keyword report) or neither organic measure can be read (since 2026-10-26).
  - **8 weeks before the Auto lane re-invests** (Kim, 2026-10-22): a search the stop-loss stepped down is not promoted
    or raised again on its own for `auto.repromote_cooloff_days` (56) after its step-down; such a row is held (Monitor),
    not parked for a person (7.2).
  - Until 2026-10-22 `plan.py` raised a stop-loss review row for every such search and a person decided.
  - **Two step-downs that don't wait for a checkpoint (Kim, 2026-11-04, decision 182).** At every run, a logged invest
    search steps down the same way (`stop_loss.step_down`: breakeven, top of search 0%, budget min(live, $5), Auto, out of
    the invest log once applied) when:
    - **its index slips** (`thresholds.slip_step_down`, on): its trusted index is under `index_hold` (0.8) on 15+ of our
      clicks, so the ladder gives it Trim. Rank money goes to searches that beat the market.
    - **it is over the rank cap** (`thresholds.rank_max_monthly_searches`, 3,000 searches a month, or 4,000 at index 1.3+ since
      decision 189): rank moved on
      smaller searches, not on big ones ([rank-effort-by-search-size-2026-11-04.md](../../../../docs/knowledge/rank-effort-by-search-size-2026-11-04.md)).
    A search the checkpoint already stepped down this run is not stepped twice. Where no owner keyword is in the run's
    report it is a held 'Stop-loss review' row (Monitor). Seasonal products keep their own weeks (section 8).
- Non-invest roles primarily use estimated breakeven economics, not a promise of realized profit. Test's $0.35
  floor no longer exceeds the keyword's breakeven click (decision 135); placements/dynamic bids and uncertain conversion
  can still change actual outcomes.
  Review actual CPC and contribution after ads. An approved learning test above the economic baseline is an
  explicit, finite investment, not something silently treated as self-funding.

## 5. Harvest (new searches)

- **What gets harvested.** Scale Insights import rule "[Bookmarks pilot] Import 1+ order and 9%+ CVR as Exact
  (ad group default bid)" (rule 21051, for gate band 9%):
  - Sponsored Products search terms with ≥1 order and conversion at or above the product's gate;
  - imported as **unique exact** keywords into the product's "Harvest Exact - SI import" campaign ($5/day).
- **Starting bid** = the harvest ad group's default bid, computed per product each run:
  - median of Amazon's suggested medians across the product's priced searches;
  - floored at the product's average breakeven click (profit × average ad conversion);
  - capped at the median suggested high.
  - Bookmarks, 2026-10-17: medians $0.485, breakeven $0.40–0.48 → $0.50 at launch, $0.47 Cross / $0.49 Scenery
    recomputed.
- **Gate** = median suggested low ÷ profit per order (the conversion a term needs to break even at the cheapest
  visible bid), rounded down to a band in `config.json harvest.gate_bands`. Each band needs one shared SI import
  rule (copy 21051, swap the criteria profile).
- **When Amazon has no ranges** after its recorded attempt (decision 106): use SoldScope's actual complete positive
  low/CPC/high ranges for exact queries in this product's terms, with the same starting-bid formula and gate bands.
  The record labels `harvest.bid_source: soldscope` and describes estimated ranges, never Amazon suggestions.
  Existing Amazon ranges take precedence unchanged. Own CPC, peer CPC and breakeven cannot invent the low/high needed
  for this gate; without actual ranges, the harvest destination remains pending.
- **Next run.** A harvested keyword is priced by its role like any other: Invest/Prove first moves it into its own
  SKC, Hold → breakeven, Test → its provisional economic bid plus the separate delivery review, irrelevant → negate.

## 5b. Sponsored Brands video (added 2026-10-18, replaces the SKC audit's SB video build)

- **Which searches:** every invest search (Invest and Prove first) gets one exact keyword in a Sponsored Brands video
  campaign the AI owns. Searches the AI's SB campaigns already hold are left there.
- **Where:** the product's live "Highest Converting Search Terms" video series, at the next number, spelled as the
  live campaigns spell it. Up to 8 keywords per campaign; the budget is the series' usual budget (Scenery $10, Cross
  $5), or `sb_video.budget` in the product file.
- **Bid:** the search's Sponsored Products invest bid (Amazon's suggested median, or breakeven if higher, never above the
  high) × `sb_video.sb_rank_ratio` (1.0), never under Amazon's Sponsored Brands minimum (`sb_video.min_bid`, $0.25; bids
  under it were rejected on 2026-10-20). A rank search keeps bidding to be visible in Sponsored Brands too (Kim,
  2026-10-25, decision 135: "be sure to continue spending and bidding more for the rank investment keywords"). Every other
  Sponsored Brands keyword is priced at Sponsored Brands' own conversion, `sb_video.sb_cvr_ratio` (0.78; Kim, decision
  135: "let's optimise sponsored brands bids at its own cvr"): over the 90 days to 2026-10-24 the AI products' Sponsored
  Brands video exact keywords converted at 12.7% (3,167 clicks, 403 orders, 83% ACOS) against 16.4% for Sponsored Products
  exact. Until 2026-10-25 both were × `sb_cpc_ratio` 1.2 (what a video click cost, $0.98 against $0.83, 90 days to
  2026-10-17), which priced SB above SP although SB converts worse. Amazon gives no Sponsored Brands suggested bids through
  MAP. No placement boost.
- **Which searches get a video waits on the promotion** (decision 135): a new video, and the holding bids of its search's
  older SB copies, take the lane of its search's Sponsored Products promotion when that is held, so a search too thin for its
  own exact campaign gets no video either.
- **Amazon's bid optimisation off** on these campaigns, so the AI is the only owner of their bids.
- **Weekly:** keywords in the AI's own SB campaigns are priced by the same roles as Sponsored Products, from their own
  Sponsored Brands clicks and orders (90 days) shrunk toward the search's conversion × `sb_cvr_ratio` (an exact keyword) or
  the product's ad conversion × `sb_cvr_ratio` (broad, phrase). Irrelevant ones are paused. A keyword with no clicks of its
  own is priced like any other since decision 168 (`inventory.no_data_raise` true, 2c); the older and paused SB campaigns
  below stay cut only.
- **Older SB campaigns** (every other consumer SB campaign of the product, since 2026-10-25, decision 135: "price the
  older SB campaigns that woke up the same way") are priced the same way and **cut only**: a bid above its price is
  lowered, never raised. A broad or phrase keyword there is Discovery, at most the product's breakeven click × the ratio.
  The run summary counts them (`sb_video.legacy_bid_cuts`).
- **One owner in SB too:** older exact copies of an invest search in other video campaigns of the product (where
  Amazon moves the bids) drop to a holding bid the day the AI's keyword is created, and are paused from the next run,
  once the AI's keyword is live in its own enabled campaign (2c; 2026-10-26: the same-run pause left 8 searches with no
  live SB exact ad while the new videos sat in moderation, and 8 more whose videos were held for a missing asset).
- **Scale Insights:** new SB ad groups go on an exact-owner strategy with no blacklist and no negative rules (as 103
  for Sponsored Products), on rule 203, once Scale Insights syncs them.

## 6. Price

A price change is a separate, reviewed decision. Compare with the best-selling packs of the same size; one change
at a time; step back if the index on invest searches falls under 1.1 within 3 weeks. Recompute `profit_per_unit`
and `economics_as_of` in the product file the same day, or every breakeven bid is wrong (this happened on the
pilot: Scenery's launch bids used the $8.99 economics on the day the price moved to $9.99).

## 7. Who has to say yes (added 2026-10-19, Kim's decisions of that day)

Sections 1 to 6 decide each change's role and price. This section decides only **who has to approve it**. Nothing here
changes a role or a bid formula.

- **The design** is `docs/superpowers/specs/2026-10-19-bid-auto-apply-design.md` (cited below as "spec"). Read it for the
  reasons behind each rule. **Since 2026-10-22 autonomous runs** (`docs/superpowers/specs/2026-10-22-autonomous-runs-design.md`,
  decision 98) replaced its human list (7.2, 7.9), its shadow mode and the Nov 9 gate (7.11): the run applies its own Auto
  rows, and only the human list is parked "For human".
- **Every number** is in `config.json` → `auto`, and a product's own `auto` block overrides it.
- **The code** is `scripts/lanes.py` (the rules), `scripts/plan_lanes.py` (running totals, bands, locks) and
  `scripts/evidence.py` (confidence and opportunity). If you change a rule, change those and this page together.
- **The weekly steps** are in [weekly-run.md](weekly-run.md).

### 7.1 The evidence ladder (spec 3, Kim 2026-10-19)

Raises and promotions go by orders and index, not by a probability bar.

| Call | Evidence | About how sure, at a 10% market (2026-10-19) |
|---|---|---|
| Promote to **Prove first** (its own exact campaign, the small budget, +30% top of search, its SB video) | 2 orders and index ≥ 1.1 since 2026-10-31 (decisions 174 and 178; 1.25 until decision 178; 3 orders from 2026-10-25, decision 135; 2 before). Orders are the higher of the search's SQP purchases and its search-term report ad orders | lower than the 60% it was at 1.4 (Kim accepted the trade, 2026-10-21, and again at 1.1 on 2026-10-31) |
| Promote to **Invest** | 3+ orders and index ≥ 1.1 (section 2's Invest rule) | about 50% at exactly 1.1, more as the index rises |
| **Raise** a bid above breakeven, outside Invest | 3+ orders and index ≥ 1.4 | about 65% |

- **Why a lower certainty is acceptable:** Kim's view is that 3 to 4 orders at 1.4x is good enough. A wrong promotion is
  bounded by its standard budget ($10/day Invest, $5/day Prove first), the stop-loss (section 4, applied by the run itself
  since 2026-10-22), the 8-week cool-off after it (7.2) and the 24-hour spend check ([weekly-run.md](weekly-run.md),
  "Day-1 check"). The investment band bounded it too until decision 100 (2026-10-22); it is information since (7.5).
- **The probability is still computed and shown** on every row, as words: "about 65% sure it beats the market". A cut
  reads "converts under 0.8x the market". A person reading the dashboard sees how strong the evidence is.
- **Not time-bound.** Niches move at different speeds, so a promotion waits for evidence, never for a calendar date.
- **A search with no same-query market benchmark has IDX unknown** (section 1). It is never promoted (except the
  early-stage fallback to Prove first, section 10), and it has no opportunity.
- **Product targets** use the same ladder against the product's own ad conversion (section 2b).
- **The Prove first bar (Kim decided 2026-10-21; config changed 2026-10-22):** it read 2 orders at index 1.4. Kim:
  "we can be more aggressive at 2 orders with 1.25 idx and above". The certainty at 1.25 is lower than at 1.4 and he accepted that; it is still
  computed and shown on every row. The Invest bar (3 orders at 1.1) and the raise bar (3 orders at 1.4) stay. The same
  1.25 was the bar for the search-term fallback and the Discovery cap lift (section 10.3); all three are 1.1 since decision 178.
- **Three orders before a search gets its own campaign** (Kim, 2026-10-25, decision 135: "#11 - ok then" on fix 11 of
  the AI spend review, "fewer $5-a-day campaigns on thin evidence"): `prove_orders` and `fallback.prove_orders` went from 2
  to 3, and the two-SQP-week check (10.3, item 1) applies at every stage, not only in early. The 2-order bar at 1.25 stays
  for the Discovery cap lift (a bid on an existing keyword, not a new campaign).
- **Two orders again** (Kim, 2026-10-31, decision 174: "Validated = 2+ orders, so drop the Prove-first order bar from 3
  to 2"): `prove_orders` and `fallback.prove_orders` 3 → 2. A search with index ≥ 1.25 (1.1 since decision 178, below) and 2+ orders gets its own
  single-keyword Prove-first rank campaign, +30% top of search and its SB video. Orders count from the SQP purchases or
  from the ads search-term report (Kim, 2026-10-30: "ad data counts too"): `lanes._ladder_orders` takes the higher of the
  two, because SQP's purchases already hold the ad-attributed ones and a sum would count them twice. That count is used by
  every rung (Prove first, Invest, the raise bar); the confidence words keep the index record's own orders and clicks. A
  business (B2B) record still counts only its own B2B orders. The Invest bar (3 orders at 1.1) and the raise bar (3 orders
  at 1.4) stay: nothing in this rulebook ties them to `prove_orders`.
- **Prove first at 1.1** (Kim, 2026-10-31, decision 178: "I thought it was supposed to be 1.1. And then anything above
  1.1, we will kind of rank or approve first"; he chose the recommendation that also sized the launch test, 2i):
  `prove_index`, `fallback.prove_index` and `discovery.cap_lift_index` 1.25 → 1.1. The index is shrunk toward the market,
  so on 2 orders 1.1 and 1.25 are close, and the bar now matches Invest's. A wrong Prove first is still bounded by its
  $5/day, the stop-loss and the 8-week cool-off.
- **Config:** `prove_orders` 2 since 2026-10-31 (3 from 2026-10-25 to 2026-10-31; 2 before), `prove_index` 1.1 since 2026-10-31 (decision 178; 1.25 from 2026-10-22; 1.4 before), `invest_orders` 3, `invest_index` 1.1, `raise_orders` 3, `raise_index` 1.4.

### 7.2 Three lanes (spec 5)

| Lane | Which changes | What happens |
|---|---|---|
| **Auto** | Everything that can be written, inside every guardrail, except the human list (7.9) | Applied by the run itself with no approval, during the audit (autonomous runs, 2026-10-22). Read back, recorded, published as applied, and counted in the run's Slack recap |
| **For human** (the dashboard's "Needs human") | The human list (7.9) only: no bid or rank call since decision 107 | Parked: one Bids item per ASIN on the dashboard, biggest opportunity first, and one line in the run's Slack message tagging who decides (`notify.py`). Applies only after approval, at the levels in 7.10 |
| **Monitor** | Every close-call raise and promotion, whatever its opportunity (7.6, decision 107); a raise past a product's own raise count (none since decision 164); a stop-loss with no step-down yet and a row with no bid; every row of a product whose data isn't fresh (7.9); a promotion in an early product's volatile week or first SQP week (section 10); a row that re-invests in a search the stop-loss stepped down less than 8 weeks ago (the cool-off, below) | Held back: written to `payloads/held/` only, listed on the product page, re-judged at the next run. Not escalated |

`lanes.classify` takes the first rule that applies (since 2026-10-22):
1. A lock (7.8): **For human.** Stale data (7.9): the run stops up front on an Auto product (decision 168), **Monitor** in
   shadow. An onboarding product and a seasonal phase switch are
   judged like any other (until 2026-10-22 both were Needs human).
2. A stop-loss step-down (section 4): **Auto.** Then the re-investment cool-off (Kim, 2026-10-22): a row that invests
   in a search again (a promotion, a business new exact keyword, a raise of an Invest or Prove-first bid, an Invest or
   Prove-first 'Budget and top of search' row) within `auto.repromote_cooloff_days` (56) of the search's stop-loss
   step-down (its `invest_history` or `business_invest_history` entry's `ended` date) is **Monitor**: "stepped down at
   stop-loss on <date>; held from re-investment until <date + 56>". After the 8 weeks it is judged on the ladder as usual.
3. A listing price: **For human.** A stop-loss review (no step-down could be written yet): **Monitor** (decision 107; For
   human until 2026-10-23). The executable rows that are not judged on their evidence (7.9): **Auto**, except a Scale
   Insights rule set beyond the standard setup and a row that can't be written. A 'Budget and top of search' row with a
   budget or boost other than its role's standard is written at the standard by `plan_lanes.standardize` (decision 107;
   For human until 2026-10-23); a budget the product file's `budget_overrides` sets for the search is its standard.
4. A cut (7.3).
5. A promotion (7.5), a business invest search's new exact keyword among them. A consumer promotion, and a live rank
   campaign's policy-only top-of-search row, first pass the data-stage checks of section 10.3 (the head-term flags: For
   human; the fallback: Auto, a Prove-first test, since decision 107; a volatile week in early, and one SQP week at every
   stage since decision 135: Monitor).
   `plan_lanes` then writes a promotion with a non-standard budget or boost at the standard (decision 107); a member of
   its bundle a person locked parks only a promotion that would go out. No promotion is held for money (7.5, 7.7): the bands and the $60
   loss line are information on the row and the summary.
6. A raise (7.4), a Sponsored Brands one included. A raise on the live keyword of a search promoted on the search-term
   fallback is Monitor (decision 107; For human until 2026-10-23): the fallback never raises (section 10.3, item 2).
   (From 2026-10-23 to 2026-10-25 a Hold keyword's raise to breakeven +15% at index 1.0-1.1 was its role's price, so Auto,
   decision 108; the test ended with decision 135 and Hold bids breakeven.)

### 7.3 Cuts: always Auto, with exceptions (spec 5)

- **A cut to the rulebook price or below goes to Auto, whatever its confidence or opportunity.** A bid at or below
  breakeven can't lose money on the click. That includes Scale Insights' 121 imports and the out-of-plan sweep. A cut is
  never Monitor.
- **No exception since decision 168** (decision 168, Kim, 2026-10-29, "the full package"): `big_cut_pct` is null, so a big bid cut on a proven search goes straight to
  its price too. From 2026-10-22 to 2026-10-29 a cut of more than 50% (`big_cut_pct`) on a search with 3+ orders
  (`big_cut_orders`) was the one exception: it stepped down 50% a run (decision 107; For human before). A number in
  `big_cut_pct` brings the step back. A pause, with orders or not, is
  Auto (the guard reads bid cuts only), and so are a cut on an Invest or Prove-first search and a cut or pause on a search
  the team invests in: the planner's roles and the stop-loss (section 4) are their exits. Such a cut still carries
  `invested_search: true`; one that goes out from `auto/` does not take the search out of the invest log (only a
  person's cut or the stop-loss step-down does), so its spend stays in the product's planned invest. The exceptions below
  were the rules from 2026-10-20 to 2026-10-22.
- **Exceptions until 2026-10-22, which went to Needs human because they risk rank, not money:**
  - a cut on an Invest or Prove-first search;
  - **a cut or pause on a search the team invests in** (fix E, 2026-10-20): one in the product's `invest_log`, or an
    invest (rank) search this run, whatever its role this week. A logged search whose index slips to Hold or Trim is
    still invested: its exit is the 4-6 week stop-loss (section 4), not a weekly wobble. The row reads "the team is
    investing in this search; cuts and pauses go through the stop-loss review", carries `invested_search: true` and is
    the book owner's call (7.10; it was Lee's until 2026-10-22). A promotion's own duplicate pause is not one: it
    moves the search into its new campaign and shares the promotion's lane.
    **A search leaves the invest log only by a person's step-down** (fix G, 2026-10-20). `log_invest.py` never drops it
    on its own: only when this run's stop-loss review of it was approved (approvals records the approval in
    `payloads/approved_decisions.json`), or a cut or pause on it flagged `invested_search` went out from `approved/` or
    `review/`. Until then it stays logged ("not a rank term this run; kept until the stop-loss review decides"), so this
    rule keeps holding and its spend stays in the product's planned invest (7.7);
  - a cut of more than 50% (`big_cut_pct`) on a search with 3+ orders (`big_cut_orders`), while `big_cut_pct` is set (null
    since decision 168);
  - pausing a keyword that has orders.
- **The checks in rule 1 come first.** A cut on a locked row waits for a person; a missing or unreadable inventory cover stops the run (decision 168); old SQP
  doesn't (decision 172).

### 7.4 Raises: which are Auto (spec 5a; no step or count since decisions 164 and 165)

A raise is Auto when it is any of these:
- up to the search's breakeven click (it can't lose money on the click by construction);
- up to the suggested mid of a validated or launch-test ordinary keyword (section 2i, decision 177; `lanes._raise_lane`);
- an Invest or Prove-first re-price inside Amazon's suggested low to high range;
- above breakeven with the ladder's evidence: 3+ orders at index ≥ 1.4.

The caps:
- **No step since 2026-10-29** (`max_raise_pct` null; Kim, decision 165: "i want bids to reach their correct price way
  quicker ... as long as we lock down the bids calculations accurately, we should go ahead and just do the adjustments,
  don't put the limit"): a raise goes to its price in one run. Until then +25% a run (`max_raise_pct` 25), rounded down to
  the cent, never less than one cent more than now (that minimum stopped at breakeven), the bigger raise written at the cap;
  a number restores that step. Which raises are Auto is unchanged (the three bullets above); close calls stay Monitor.
- **No count of raises a run** since 2026-10-29 (`max_raises` null; Kim, decision 164: "lift the 20-raise caps. let suggested validated raises through"). Until then 20 automatic raises a run, the rest held (Monitor) for the next run with their cap kept (decision 107). A number in `max_raises` (config or a product file) restores a count cap.
- **A person's approval of a capped row also writes the cap.** Someone who wants the full raise approves it next run.

A raise above breakeven without the ladder's evidence is a close call (7.6).

### 7.5 Promotions, bands and the loss line (spec 4, 5a; information only since decision 100)

- **A promotion** is a "New exact campaign" or "Reuse exact campaign" row. Inside the business kind a "Business
  invest" row is one, and so is a business "New exact keyword" row (always a person's call until 2026-10-22; judged on
  the ladder since, once its campaign and ad group are known, section 9.4).
  Its bundle (the duplicate pauses of that search, its funnel negatives and its budget row) shares its lane. The campaign starts at the standard budget ($5/day Prove first,
  $10/day Invest) and the standard top of search: the standing rank policy's +50% Invest or +30% Prove first (section 2,
  2026-10-20), or 0% when `placement.rank_tos_standing` is off. A promotion with any other budget or boost goes to a person.
- **A big search bids the suggested low (decision 182, Kim 2026-11-04: "cut to amazon's suggested low .. instead of
  breakeven").** The exact keyword of a search over the cap that beats the market (Defend, `over_rank_cap`) bids the
  higher of its breakeven and the suggested low (Amazon's, else SoldScope's or the estimate once Amazon was tried; such
  searches join `need_suggested_bids.json`), never raised; a logged invest search over the cap steps down to that low.
  Broad and phrase keywords of the search keep breakeven.
- **A product's own cap (Kim, 2026-11-04: invest in low and bottom-mid searches first, "build up the reviews counts and
  variation optionalities", then "when it is 'time', we try going for the bigger search volumes").** A product file's
  `rank_max_monthly_searches` overrides the threshold for that product; a person raises it when the listing is ready.
- **A volume cap, not a money cap (Kim, 2026-11-04, decision 182; sized by decision 189, 2026-11-05).** A search over
  `thresholds.rank_max_monthly_searches` (3,000 searches a month since 2026-11-05; 2,400 on Nov 4, and 1,600 for a few hours
  before that) is never Invest or Prove first: it bids Defend (the term's `over_rank_cap`, `rank_cap`, `monthly_searches`
  and `rank_cap_sources` say why). The volume is the highest of: the search's SQP volume scaled to 30 days (the launch
  list or SoldScope for a search with no SQP row); DataDive's Rank Radar volume in the product file's `rank` block;
  SoldScope's monthly volume when the run has `soldscope_volume.json` (`stage.cap_volume`; cross-checked on Kim's ask,
  2026-11-04). Each source counts at its own number: decision 189 dropped the 0.8 DataDive conversion (Kim: "it
  confuses teammates anyway"), because on the runs to Nov 5 SQP read about the same as DataDive (81 searches, median
  1.02), not 0.8 of it. B2B invest searches (section 9) are not capped.
- **The strong-index band (Kim, 2026-11-05, decision 189: "3,000 cap; index 1.3+ to 4,000").** A search with a trusted
  index of `thresholds.rank_cap_strong_index` (1.3) or more is held to `thresholds.rank_cap_strong_max` (4,000) instead,
  or to the product's own cap when that is higher (`stage.rank_cap_for`). It converts well enough that each click pays
  back faster. It is still taken out by the index slip (under 0.8 on 15+ clicks), and if its index drops under 1.3 while
  it is over 3,000, the cap steps it down at that run.
- **No money cap on validated promotions (Kim, 2026-10-31, decision 174: "invest in validated keywords without a money
  cap").** `auto.invest_guide_month` ($2,000) and `auto.max_loss_month` ($60) are flags in the run summary and the Slack
  recap only: nothing parks, holds or shrinks a promotion because of them (as since decisions 99 and 100).
- **A rank campaign that runs out of budget steps up (decision 174).** The budget headroom check
  ([budget-headroom.md](budget-headroom.md)) judges the product's Invest and Prove-first campaigns without its ACOS
  condition: out of budget on 5+ of the last 14 days (`min_capped_days`) is enough for +50% (`step`, at least `min_step`),
  never past `max_budget` ($50/day) or Amazon's suggestion, judged again after `review_after_days` (7). Losses are accepted
  for ranking, so it never steps back on ACOS; the stop-loss (section 4) is its brake. A stepped budget is the campaign's
  standard from then on (`rank_budget_step`), so the invest step's $5/$10 never undoes it. Non-rank campaigns keep the ACOS
  condition (out of budget at ≤ 80% of breakeven ACOS with 3+ orders).
- **A live rank campaign's top of search (Kim, 2026-10-20: "don't file it under Needs Human").** A "Budget and top of
  search" row whose only change is top of search set to the standing policy, with the budget unchanged
  (`policy_tos_only`, set by `placement_review.hold_defaults`; `lanes.policy_tos_only` reads it with the row's own budget),
  is no longer always-human. After the lock, fresh-data and onboarding checks it is judged like a promotion: the ladder for
  its role (its own search's band is information: the reason names a search past the $60 loss line, and the row is
  flagged `over_loss_line`). It adds nothing to the planned invest (the campaign is live, so its spend is already
  planned). Any other budget or top of search that isn't the standard is written at the standard since decision 107 (2026-10-23;
  a person's call before). Its approval level
  is the book owner's (Kim's when past his $600 level until decision 99, 2026-10-22).
- **A search's band:** what it costs to win the target share of that search's clicks (`rerank_click_share_target`, 10%
  today): monthly clicks × share × the invest bid. Bands scale with the niche; they replace the flat +$50/month of the old
  playbook.
- **Shrunk by modelled loss, per search (Claude's call, spec 4):** a band tied to volume could fund a big head search that
  converts only at market. So a search whose modelled loss (the re-rank's `net`) is worse than **$60 a month**
  (`max_loss_month`, the loss line for one search) gets a smaller band, sized so the modelled loss is $60.
- **A product's band** is the sum over its invest searches, less the invest spend already planned on its other invest
  searches. The promotions take their spend from it biggest opportunity first.
- **Information only since 2026-10-22** (decision 100, on Kim's words of decision 99: "don't cap the promotion because i want good keywords to be
  invested on" and "we don't want to put a cap and hamper the autonomous engine. if spend is overboard, the humans will
  notice it and step in anyway"). A promotion on the ladder goes out whatever its bands say. Its reason says how it sits:
  "it fits the product's monthly invest band ($X of $Y left)", or "it goes past the product's monthly invest band ($X,
  with $Y left)" and "modelled to lose $X a month, over the $60 loss line for one search", each followed by "(information
  only: no cap, decision 100)". A promotion with no modelled spend goes out unsized ("its monthly spend isn't modelled, so
  it isn't sized against a band"). The row is flagged `over_invest_band` and `over_loss_line`; the run summary lists the
  Auto ones (`over_invest_band`, `over_loss_line`) with `invest_band_month` and `loss_line_month`, and the Slack recap
  says "Past the product's $X/month invest band: <searches>" and "Modelled to lose over the $60/month line for one
  search: <search> ($X/month)". A person who finds it overboard steps in (a decline, or the product's kill switch).
- **Until 2026-10-22** a promotion over its own search's band went to a person ("modelled to lose $X a month, over the
  $60 limit for one search", checked before the product's band), so did one the product's band couldn't fund ("the
  product's monthly invest band is short"), and so did one with no modelled spend or no band of its own.
- **What you will rarely see (2026-10-19, after merging the delivery review):** the visibility review keeps searches in the
  invest log or in `proposed_rank_experiments` at their live bid, so "re-price an existing invest search" rarely fires. A
  promotion needs SQP market clicks, so the SoldScope band fallback rarely matters.

### 7.6 Opportunity, and when a person gets pinged (spec 4, 9)

- **Opportunity = index × monthly searches** (monthly searches = SQP volume ÷ observed days × 30). `plan.py` and
  `market_review.py` use the same function.
- **A close call is one the evidence doesn't settle** (a raise or promotion below the ladder). Since 2026-10-23 (Kim,
  decision 107: "the bid changes and rank investments are all actually programmatically calculated and quantifiably
  decided") it is the AI's "not yet": Monitor whatever its size, and the next run judges it again on more data. Its
  reason still names its opportunity. Until then one with an opportunity of at least **300** (`min_opportunity`), or with
  no volume and more than **$15** spent in 30 days (`monitor_spend_cap`), went to Needs human; both settings are now
  only read for that history.
- **No volume** (product targets, searches without SQP volume): no opportunity; the reason names its 30-day spend.
- **Monitor is not a rejection.** The row is held back (never in `auto/` or `review/`), listed on the product page, and
  judged again next run. There is no raise cap since decision 164.

### 7.7 The investment guide: $2,000 a month a product, a guide, not a gate (Kim, 2026-10-22, decision 99)

- **Kim, 2026-10-22:** "its ok to invest $1800 to $2000 per ASIN per month, spread over $60 to $70 per day. don't cap
  the promotion because i want good keywords to be invested on." And the same evening: "we don't want to put a cap and
  hamper the autonomous engine. if spend is overboard, the humans will notice it and step in anyway."
- **The guide** is `auto.invest_guide_month`, $2,000 of planned invest spend a month on one product. It is information
  only: no promotion is parked "For human", and `approvals` holds no approved row, for its money.
- **What the run shows.** The planner starts from the invest spend already planned on the product's other invest searches
  (`planned_invest_month_start`), including a search in the invest log that is no longer a rank search, at its recent
  monthly ad spend (its 90-day ad spend ÷ 3): its campaign keeps spending. It adds the modelled monthly spend of the
  promotions that go out on their own. The run summary carries `planned_invest_month`, `invest_guide_month` and
  `above_invest_guide`, and the Slack recap adds "Planned invest $X/month (above the $2,000 guide)" when it is above. A
  person who finds the spend overboard steps in: a decline on the dashboard, or the product's kill switch (7.12).
- **The program total** (`summary.program`, `autonomy.program_month`) is information only too: every other product file's
  planned invest (each file's `planned_invest.month`, which `log_invest.py` records after an apply as the plan's
  `planned_invest_month_start` plus the promotions that went out; a file without one counts its invest log at the
  standard budgets, $10 a day an Invest search and $5 a Prove first, an upper bound) plus this product's. On 2026-10-22
  no product file had a `planned_invest` record yet, and the estimate summed to $49,050 a month over the 24 product files
  that invest (`python scripts/autonomy.py program --asin <ASIN>`); it falls as each product's applied runs record theirs.
- **What still bounds a promotion:** the evidence ladder (7.1), the standard budget and boost (7.5), the locks (7.8),
  the stale-data holds (7.9), no raise count or step since decisions 164 and 165 (7.4), the 8-week re-investment cool-off (7.2), the
  stop-loss (section 4) and the guards (7.12: the Day-1 spend check, the read-back). Its search's band, the $60 loss line
  and the product's band are information, like the guide (7.5).
- **The goal it serves** (Kim, 2026-10-22): "my goal is to get about 50% organic to 50% ppc units ordered.. or at least
  about 60% organic to 40% ppc". A product is on goal at 50% organic units or more and profitable after ads; 60/40 is the
  stretch target (`config.json` `goal`). A product that ranks well earns its investment back as organic share grows.
- **Until 2026-10-22** (kept for the record): Kim's $600 a month a product (`kim_product_month`) was a gate. In
  opportunity order, a promotion that took the product's running total past it was flagged `past_kim_level`, with its
  bundle, was never Auto, and only Kim's approval released it; `approvals` checked it again. For a few hours on
  2026-10-22 a $3,000-a-month program level (`kim_program_month`, `past_program_level`) did the same for the whole
  program. Decision 99 removed both.

### 7.8 Locks: a person's decision holds its row for 4 weeks (spec 6)

- **What locks a row:**
  - a declined or approved row, for 4 weeks (`lock_weeks`);
  - a search with an approved rank experiment, until its review date; one still proposed holds its search too ("a person
    decides it first");
  - a creation that went out (a create lock): it is never emitted again, whatever row id it went out under. **A
    Sponsored Brands video build is created once** (fix G): once any row of a build (its campaign, ad group, video ad and
    keywords) is recorded, the build's other keywords get create locks too, and any keyword of that campaign is added to
    it by hand, never by handing the build out again.
- **Where they live:** the product file's `decisions` list (`id`, `what`, `by`, `on`, `until`, `direction`). Entries more than
  90 days past their end are pruned.
  - A decline lock is written by `approvals`, and also read from the run's saved `reviews.json`.
  - An approve lock is written by `applied`, once the row went out of `approved/`.
  - A create lock is written by `applied` for a creation from any folder.
- **Direction-aware.** A lock holds only the moves it would be wrong to repeat or undo:
  - a declined move holds the same move (a declined cut also holds a pause, and the other way round); a different move is a
    new call, planned as usual;
  - an approved raise holds a cut or a pause, and an approved cut holds a raise: the way back would undo it;
  - an approved pause, or any other approved change, holds every move;
  - a lock with no direction (an older entry or a rank experiment) holds every move.
- **A locked row never enters the Auto lane.** It goes to Needs human and to `payloads/held/`.
- **Visible on the item.** A locked row stays on the Bids item, read-only, with `locked_until`, `lock_by`, `lock_on` and
  `lock_decision` ("Decided by Kim on 2026-10-12: decline; holds until 2026-11-09") and `lane_unlocked`, the lane it would
  have had without the lock.
- **Approving a held row again.** A person can approve a held bid or pause row again. That is a new decision: it applies,
  and its approve lock replaces the old lock when it goes out. Any other held row type can't be approved while held, and
  nor can a row a rank experiment holds (fix G): `approvals` holds that approval, "a rank experiment holds this search
  until its review", as the card offers no Approve.
- **Overriding a decline needs the decliner's level** (fix E, 2026-10-20). Re-approving a row a decline holds needs a
  signer whose rank is at least the higher of the row's own level (7.10) and the decliner's: Kim when Kim declined,
  Lee when Lee declined, a book owner otherwise. The Bids item shows that level as the row's approval level, and
  `approvals` enforces it ("needs Lee's approval: Lee declined it (approved by Sam)"). An approval held this way
  releases nothing: the decline still holds the row.
- **The same rule holds inside one week's item** (fix F, 2026-10-20). A later approval on the same item replaces a decline
  only at the decliner's level (and the row's); below it the decline stands, its lock is written and the approval is held
  ("declined by Lee; needs Lee's approval to change it (approved by Sam)"). A later decline from anyone still
  replaces an earlier approval. The card says it too: "Recorded; Lee's decline stands unless Lee approves".
- **The highest-ranked decline sets the bar** (fix G, 2026-10-20). Of the declines on a row since the last approval that
  counted, on one item and across weeks while its lock holds, the one from the highest rank decides who may approve the
  row again. A later, lower-ranked decline never lowers it: if Lee declines and Sam declines too, Sam's approval is
  still held, and the decline lock and the Bids item name Lee. A decline from the same or a higher rank replaces the
  earlier one.
- **How the planner reads the saved decisions** (`reviews.json`, which can't show a row's level): a decline on an item holds
  its row for 4 weeks unless a later approval on that same item is signed by Kim; on an item, the highest-ranked decline
  is the one that names the lock. Where two declines hold one row (the product file's and a saved one, or two weeks'
  items), the lock lasts as long as the longer one and names the higher decliner while that one still holds the same move.
  Once the row's approval goes out, its approve lock (written by `applied`, later and longer) holds instead.

### 7.9 Fresh data, onboarding and the human list (spec 5b, 6; autonomous runs, 2026-10-22)

Without these, an Auto product's run stops up front with what to pull again (decision 168, Kim, 2026-10-29, "the full package"): a run that held every row
(Monitor) read as a trip to the team. In shadow every change is held (Monitor). Until 2026-10-22 it went to Needs human. **Stock policy, since 2026-10-31 (Kim, decision 174):** stock cover of 14 days or less (`plan_lanes.LOW_STOCK_DAYS`) parks every **increase** "For human" (a promotion with its bundle, a raise, a new SB video, a budget step up, a budget or top of search that goes up: `plan_lanes.is_increase`), unless a person cleared the product: the product file's `stock_clearance` (`{"by", "on", "why", "until"}`, 7 days from `on` without `until`). Cuts, pauses and holds still go out, and the "Reorder stock" item still opens. `summary.stock_reorder` carries `cover_days`, `held` (row ids) and `cleared`. B0SAMP0015, 2026-10-31: Kim cleared it because supply chain was on it. From 2026-10-24 to 2026-10-31 low stock was an inventory alert only and held nothing:
- **SQP of any age** (decision 172, Kim, 2026-10-30): the run plans on the newest SQP it has and reports its age
  (`summary.sqp_age_days`); a seasonal product adds last season's SQP (section 8). Until then SQP over 10 days old, or
  undated, stopped the run.
- **Fresh data:** readable inventory coverage
  (`inventory_cover.json`, [data-pull.md](data-pull.md)). **While a product's Auto lane is on**, a missing or unreadable
  inventory cover file is stale too (fix E, 2026-10-20). Each reason names what to pull again ("pull the SQP pages again
  (Scale Insights get_search_query_data ...)", "save inventory_cover.json ..."). In shadow a missing file changes nothing.
- **A recent price change holds nothing since decision 168:** the run prices every row at the new settled profit straight
  away. Until then a change in the last 14 days (`price_change.json`) held every row, and that file was required too.
- **Onboarding or the first 2 weeks on AI** (registry stage `onboarding`, an onboarding run, `owner_since` under 14 days
  ago, or no readable `owner_since`) is reported in `summary.onboarding_reason` only since 2026-10-22: onboarding a
  product Kim added to the AI program applies on its own (decision 98). Until then it sent every change to a person.

**The human list since 2026-10-23** (Kim, decision 98: "only when it encounters very difficult situations and decisions
it can't resolve then park them 'for human'"; decision 107: bid and rank calls are the AI's), however confident. Taken off
on 2026-10-23: a non-standard budget or boost (written at the standard), a borderline close call (Monitor), a big cut on a
proven search (a 50% step until decision 168, straight to its price since), the search-term fallback (a Prove-first test), a raise past a product's own raise count (none since decision 164), a bid row with no
bid and a stop-loss with no keyword to step down (held for the next run):
- a listing price (Kim's);
- a row a person's decision or a rank experiment holds (7.8);
- a head-term flag: a one-word or unlisted search's promotion (section 10.3, item 4);
- a Scale Insights rule set beyond the standard AI setup (a row carrying `si_beyond_standard`; strategy144 was created
  and verified on 2026-10-22 as id302500 during Kim-approved four-ASIN completion: no bid/import/negative rules or blacklist, rule203);
- a row that can't be written: a new Sponsored Brands video campaign without a video asset, a business new exact keyword
  without its B2B campaign or ad group, a type the lanes don't know;
- the guards' items (rulebook 7.12): a read-back mismatch, a Day-1 spend trip, a Scale Insights step the
  browser couldn't do.

Everything else that can be written is Auto: budgets and top of search at the standard settings, budget steps, funnel
negatives and archived negatives, harvest default bids and setup, the standard Scale Insights rules and setup (no-bid-rule
strategies, exact owners off the blacklist, the blacklist rescue and whitelist, the harvest import rule; done in the
browser from `scale_insights_steps.json`), Sponsored Brands bids (no raise step or count since decisions 164 and 165),
pauses and new video campaigns, pauses with orders, every cut but the big one, the stop-loss step-downs, onboarding
products' rows and seasonal phase switches. Money is not on the human list: a promotion past the $2,000 investment
guide, the product's band or the $60 loss line for one search goes out and is named in the Slack recap (7.5, 7.7; until
decision 100 one past a band went to a person, and until decision 99 one past Kim's $600 a product or $3,000 for the
program to him).

Standard onboarding includes effective dayparting 203 / 21246 on every AI-controlled SP/SB/SD group, replacing
legacy direct schedules while preserving shared exclusions and explicitly approved schedule exceptions (Kim,
2026-10-24). Verify exact-ID coverage; this standard assignment needs no separate dayparting approval.

Not rows at all, and still Kim's: a price change, non-standard dayparting or a Scale Insights rule set beyond the standard setup, and
taking a product out of the AI program. Adding one is any book owner's (decision 172, 2026-10-30).

**Always human until 2026-10-22** (kept for the record):
- budgets and top-of-search changes other than a promotion's standard ones and a live rank campaign's top of search set to
  the standing policy with its budget unchanged (7.5), and every 'Budget step' (budget headroom, Kim 2026-10-20:
  [budget-headroom.md](budget-headroom.md); every step, whatever its size, is the book owner's since 2026-10-22);
- negatives, and the negative audit's blacklist rescues;
- stop-loss reviews, and demoting a search from Invest (a cut or pause on a search the team invests in, 7.3);
- listing price, Scale Insights rules and setup, harvest default bid and setup, and new exact keywords;
- anything on Sponsored Brands (bids, pauses, video campaigns);
- pausing a keyword that has orders;
- a promotion past its band or past $600 a month;
- seasonal phase switches (`docs/seasonal-bidding.md`, section 8 below): a run whose season phase differs from the
  product file's `season.phase_applied` sends every change to a person, the book owner (Lee's level until
  2026-10-22).

### 7.10 Who approves what (spec 9; sweep-playbook "Approval levels"; Kim, 2026-10-22)

Each row on the Bids item carries the level that must approve it; the item's level is the highest of its rows.

**Since 2026-10-22 the book owner approves every bid call on their own products** (decision 95). Kim: "make it such
that the book owners have more autonomy .. they're allowed to make the invest/cuts/stop loss etc." A bid row is either
the owner's or Kim's; none starts at Lee's level. Lee, the team leader, keeps the harder product calls, which
are not bid rows: when to revamp a product's images, when to cut (stop or discontinue) a product, and when to improve its listing or
offer (the `listing` items on Needs human, still at her level). Only who approves changed: the lanes, shadow mode and
everything else in section 7 are as before.

| Level | Rows |
|---|---|
| **owner** (the book owner) | Every bid row on their own products that is not Kim's: bid and target-bid changes, harvest prices, pauses with orders, raises without the ladder's evidence; promotions and their bundles, whatever their monthly spend (decision 99); any cut or pause on an Invest, Prove-first or invested search (7.3), duplicate pauses included; stop-loss reviews; 'Budget and top of search' rows (a policy-only one too, 7.5); budget steps of any size; Sponsored Brands video campaigns and SB keyword pauses; relevance negatives and blacklist rescues ('Scale Insights setup'); 'Scale Insights rules' rows (the standard AI setup: bid rules off, the guardrail strategies assigned); every row of an onboarding product; every row of a seasonal phase switch |
| **Lee** | No bid row of its own. A row Lee declined asks for her again (7.8), and the `listing` items on Needs human are hers |
| **Kim** | Listing price rows, and since 2026-10-22 a Scale Insights row beyond the standard setup (`si_beyond_standard`). Until decision 99 (2026-10-22) also a promotion past the product's $600 a month (`past_kim_level`), with its bundle, and for a few hours a promotion past the program's $3,000 (`past_program_level`); an old plan's flag now changes nothing |

Kim's other calls are not bid rows and stay his: price, hours beyond the standard 203 onboarding assignment and the Scale Insights rule set beyond the
standard setup, taking a product out of the AI program (any book owner adds one, decision 172), the rulebook and `config.json` settings, and turning a
product's Auto lane back on after a guard switched it off (7.12). Since 2026-10-22 these levels apply only to the rows
parked "For human": the Auto rows go out without anyone's approval (decision 98). The run's Slack message tags the person
each parked item needs: Kim for a price and Scale Insights beyond the standard setup; Lee for a listing, image or
offer change or cutting a product; the book owner for the rest.

Until 2026-10-22 Lee's level held promotions and their bundles, cuts and pauses on invested searches, stop-loss
reviews, budget and top-of-search changes, budget steps worth more than $50 a month, Scale Insights rules and setup,
Sponsored Brands video and SB keyword pauses, and every row of an onboarding product or a phase switch.

- **`approvals` enforces it.** A Kim row needs Kim's signature. A Lee row (one she declined) needs Lee's or
  Kim's. An owner row needs anyone who signed with a personal token. A row a decline holds needs the decliner's level too, the highest-ranked
  decliner's when several declined (7.8). A wrong-level approval is skipped and listed with the reason, and the Bids card
  says "Recorded; needs Lee's approval to apply" (or "Recorded; Lee's decline stands unless Lee approves"). A
  decline from anyone is honoured.
- **Names must match.** The server records the name of the personal token (the `PUBLISHERS` variable on Railway).
  `approvals` compares it, trimmed and ignoring case, with **exactly "Kim" and "Lee"**. If Lee's entry is spelled
  differently, her approvals count only as owner-level.
- **What the code can't know.** The server knows only who signed, so "owner" means any signed teammate, not that product's
  owner. Since 2026-10-22 a book owner approves the runs they built on their own products; the old playbook rule
  "nobody approves a Lee-level change to a run they built" went with the old split.
- **An approval counts only with `seen`:** the numbers the person saw on the row, which the Bids card sends: the bids, and
  the budgets, top-of-search boosts and modelled monthly spend the row commits (fix E). If any of them was re-planned since
  (money to the cent, a boost to the whole percent), the approval is skipped.

### 7.11 Shadow mode and the Nov 9 gate (spec 5, 8): superseded on 2026-10-22

**Superseded by autonomous runs** (Kim, 2026-10-22, decision 98: "turn it on for all AI products"). `config.json`
`auto.enabled` is true for every AI product; there is no gate to pass. Shadow is now only a product's kill switch (its
product file's `"auto": {"enabled": false}`, which a guard writes, 7.12): its runs plan and propose, and every row waits
for a person, as below. The rest of this section is how shadow and the gate worked from 2026-10-19 to 2026-10-22.

- **Shadow was the default** (`auto.enabled` false). Every row waits for a person. The Bids item lists every row with the
  lane the planner chose, and the team marks each row agree (Approve) or refuse (Decline) in the same flow as the approvals.
- **Agreeing with a Monitor row is an agreement, not an apply:** it writes no payload. Declining one writes a lock, and the
  next plan sends that row to a person.
- **The gate counts the automatic rows the team refused.** For each shadow run (tightened in fix E, 2026-10-20):
  1. Save the decisions again just before counting: `python scripts/dashboard.py reviews --asin <ASIN> --save
     <run>/reviews.json`. A decision made after the end-of-week save would otherwise be missed.
  2. Take the rows of the run's `plan.json` whose `lane_unlocked` is `auto`. Use the run's `plan.json`, not the product
     file: a closed item drops its rows. **A run with no such rows doesn't count toward the gate**: it proves nothing
     (every product is onboarding until about Oct 31, so those runs have none).
  3. Count only the decisions whose `item_id` is the run's own `bids-<date>`. A decision on another week's item with the
     same `row_id` is a different call: it is neither counted nor allowed to mask one. Of the run's own, the latest on each
     row wins (by `at`).
  4. A row is refused when that latest decision is a decline.
  - Our reading (2026-10-19): an automatic row nobody decided is neither agreed nor refused. "No refusals" proves nothing
    until the team has marked the run's automatic rows.
  - A whole-run yes on the preview (the `review/` route) is not a row decision, so it adds nothing to the count.
- **Turning a product's Auto lane on** is Kim's call, per product, once a shadow run has no automatic row the team refused.
  It is gated by evidence, not a date. Nov 9 is when Kim reads the counts, with the comparison against the Scale
  Insights baseline (`docs/sweep-playbook.md`, "Earning more autonomy").

### 7.12 Guardrails on writing (spec 6)

- **Kill switches:** `auto.enabled`, in `config.json` for everyone (on since 2026-10-22) and in the product file for one
  product (`false` there wins). `dashboard.py applied --folder auto` refuses a product whose Auto is off (`--record-anyway`
  records what already went out).
- **Execute during the audit on any day, through MarketplaceAdPros** for Amazon, and the signed-in browser for the standard Scale Insights
  setup (`scale_insights_steps.json`; never a Scale Insights change set on an AI-owned product, never a password typed by
  the agent). Weekends and legacy `apply_after` dates do not defer eligible Auto rows (Kim, decision 114).
- **Every row is read back,** not a sample. A real mismatch stops the folder's remaining Auto writes and opens a "Read-back"
  alert for the book owner; Auto stays on (decision 163, 2026-10-29; `guards.readback_switch_off` true restores the old
  switch-off). A read-back file that doesn't cover the folder is an input error: `autonomy.py readback` stops and writes
  nothing. `autonomy.py switch-off` still switches a product off by hand, and only Kim turns it back on.
- **The Day-1 check:** a product's spend on the first US weekday after an apply over 1.5 times its average weekday spend
  opens a "Day-1 spend" alert for the book owner, Auto staying on (decision 163, 2026-10-29; until then it switched Auto off;
  `guards.day1_switch_off` true restores that). The stop-loss and the weekly leak check (decision 175) are the brakes. Steps for
  both are in [weekly-run.md](weekly-run.md).
- **Caps per product per run:** none since 2026-10-29: no count of raises (decision 164), no +25% step (decision 165).
  Money a month is a guide, not a cap (7.5, 7.7; decisions 99 and 100): the summary and the Slack recap name a product above the $2,000 guide
  and a promotion past the product's band or the $60 loss line, and a person steps in if the spend is overboard.
- **The re-investment cool-off:** 8 weeks after a stop-loss step-down before the Auto lane invests in that search again
  (7.2).
- **One Slack message per run** in #3d-ppc-standup (C0EXAMPLE01; `notify.py`): what the run did, counts and money only,
  tagging the book owner, and a "For human" line per parked item tagging who decides. Rows parked for a person never go
  out without their yes.

## 8. Seasonal products (built 2026-10-21, Kim's go-ahead; the plan in `docs/seasonal-bidding.md`)

**The rank cap binds a rank build too (decision 185, Kim, 2026-11-04: "Yes, cap seasonal too").** A season rank search
over the rank cap (section 4's `rank_max_monthly_searches`, 4,000 at index 1.3+, sized on the highest of SQP, DataDive, SoldScope and the
season curve's `peak_searches` x 52/12) bids as Defend: its exact keyword takes the suggested low, never under breakeven,
top of search 0%, no new exact campaign and no SB video; one already in the invest log steps down at this run (top of
search 0%, the Hold budget). Season rank searches under the cap keep investing.

A seasonal product carries a `season` block in its product file, built by `scripts/season.py block` from SoldScope weekly
search volume (data-pull.md, "Seasonal products"). A product the team only harvests carries `"mode": "harvest"` (the
Christmas cards). Neither one: an evergreen product, planned exactly as before.

**The dates** (the rank searches' weeks summed; the last complete season moved onto this year's holiday):

| Date | Rule |
|---|---|
| Rank build start | The week the 80%-of-volume window opens |
| Rank build end | The day before the week the searches reach half of their peak |
| Wake | Two weeks before the rank build |
| Harvest | The day after the rank build to the day before the last mile (from the wake, without a rank build) |
| Last mile | The day before the holiday (`overrides` can move it, e.g. to Christmas's delivery cut-off) |
| Off | The holiday |
| Review by | Two weeks after the holiday |

On B0SAMP0010's SoldScope weeks these rules give the approved hand plan's dates: rank build to Nov 6, halve Nov 25, pause
Nov 26 (and 2024's curve agrees to the day).

**The payback test** before any rank build: at least 3 weeks of season (to the end of the 80% window) after the rank
build ends, and an index of 0.8 or more, judged by a person (last season's SQP, or a new listing's search terms). An
unknown index means no rank build until someone decides (`--rank-build yes --by "<who, when>"`). Kim approves a rank
build and the book owner the season dates (Lee approved them until 2026-10-22; `docs/seasonal-bidding.md`).

**What the weekly run does in each phase:**

| Phase | plan.py |
|---|---|
| Asleep, last mile, off, review | Plans nothing, and says why. These are dated steps: open items from `season.py items` (halve, pause, review, next wake) |
| Wake, harvest | No invest searches. A search that would be Rank bids as Defend, at its breakeven; no new exact campaigns; no stop-loss (nothing is invested in) |
| Rank build | The block's rank searches are the only invest searches, whatever their SQP (a new seasonal listing has none, and Rank needs 150+ SQP searches): Invest at Amazon's suggested median, top of search by the standing policy. Any other would-be Rank search bids as Defend |

In every planned phase:
- **Every exact search bids at its breakeven.** A seasonal search without SQP would be a Test (market default) or Leave
  (low holding bid); in season it holds at its own conversion's breakeven, with the 10-click prior toward the product's.
- **No top-of-search push off the invest searches.** An exact SKC that isn't one of this phase's rank searches, with a
  live top-of-search boost, gets a "Budget and top of search" row back to 0% (budget unchanged; Auto since decision 155's placement policy, a person's
  call before).
- **Stop-loss at 2 and 4 weeks** of investing (the block's `stop_loss_weeks`), not the evergreen months 3, 6, 9 and 12
  (section 4).
- **No SQP is fine** for a seasonal product planned without any (a new seasonal listing has none).
- **Last season's SQP** (decision 172, Kim, 2026-10-30, "use last season's sqp"): when the run folder holds
  `last_season_sqp_*.json` (data-pull.md), every search this season shows is priced on this season's and last season's
  clicks and purchases together (ours and the market's), so an in-season bid isn't set on a thin early-season week.
  Volume, organic share and the roles' volume gates stay this season's; a search only last season had is not added.
- **The rank build's cap:** `summary.season.rank_build_budget_to_end` is the most the invest budgets can spend to the
  build's end; past the block's `invest_cap` ($600 by default), the summary says so. Set `budget_overrides` lower, or get
  the cap raised.

**Harvest mode** (`"mode": "harvest"`) harvests from onboarding to the last mile: before the wake, in the wake and in
place of a rank build. After the season the product sleeps like any other.

**Phase switches.** `season.phase_applied` in the product file is the phase whose changes were last applied. A run in
another phase is a switch: every change goes to a person ("the season phase changes this run"), every row at the
book owner's level, or Kim's for a promotion past his level (7.10; Lee's level or higher until 2026-10-22). Set
`phase_applied` to the new phase when the switch's changes are applied, in the same commit as the run log.

## 9. Audiences and business buyers (decided by Kim 2026-10-21; business roles and lanes decided 2026-10-21 evening, built 2026-10-21)

Kim, 2026-10-21: the AMC audiences and the Amazon Business (B2B) campaigns fold into the planner's bidding. "It's
still a campaign, same thing on the same keywords, a different audience for a different use case": each kind in its
own lane, never as copies of the consumer campaigns.
- **Phase 1** (design `docs/superpowers/specs/2026-10-21-amc-b2b-fold-design.md`, plan
  `docs/superpowers/plans/2026-10-21-amc-b2b-fold.md`, merged to main as 4ba5af2) taught the planner the shopper kinds
  and gave the B2B keywords their own conversion.
- **Business roles and lanes** (design `docs/superpowers/specs/2026-10-21-b2b-lane-and-roles-design.md`; decided by
  Kim 2026-10-21 evening, built the same day on branch `fold-business-lane`). Kim: "at the end of the day it is
  still a human at the other end of the screen". A business buyer types the same search into the same box, so the same
  rules run on the B2B keyword's own numbers: every role a consumer keyword can take, Invest and Rank included, and the
  same lanes. This section describes that build.
- **Phase 2** adds the AMC audience uplift on the consumer owner. It has its own design.

**Why business buyers get their own owner.** The B2B campaigns are Amazon-Business-exclusive: they only enter auctions
where the shopper is a business account. Over 90 days (pulled 2026-10-21) they had 9,685 clicks at $1.63 CPC, 34.6%
conversion and 30.3% ACOS. The regular campaigns had 49,742 clicks at $0.87, 15.4% conversion and 47.2% ACOS. Until
2026-10-21 the planner didn't recognise them. The Oct 17–20 runs (MarketplaceAdPros's write log, 564 change sets):
- paused 7 B2B exact keywords as duplicates;
- put 1 funnel negative in a B2B ad group;
- cut 178 Sponsored Products and 138 Sponsored Brands bids to the consumer breakeven.

All of it was repaired 2026-10-21, about 11:30–12:30 SGT, and 317 of 317 rows read back (logs/2026-10-21-b2b-repair.md).

**What differs between the kinds is the numbers, not the rules.** B2B traffic converts about twice as often, and each
B2B keyword sees a fraction of the clicks: 15 to 67 B2B clicks a product in 90 days on the three products with B2B
campaigns (90 days to 2026-10-18, pulled 2026-10-19). So the ladder's proof keeps most B2B keywords at Hold for weeks,
and only the clear converters invest. That is the intended speed.

### 9.1 The kinds, and one owner per kind (fold design 4a; roles design 4c)

Section 2's kind table says how the planner knows a campaign's kind: the live `siteRestrictions: AMAZON_BUSINESS` flag,
else the `B2B` name marker; business wins over audience. For each search the planner names up to three owners:

| Shopper kind | Owner | Its setting |
|---|---|---|
| Consumer | The planner's campaign for the search: the SKC, the harvest exact or the Hold campaign (section 3) | Its bid by the roles of section 2. The AMC audience uplift on it is phase 2 |
| Business | The enabled B2B exact keyword for the search with the most clicks in 90 days, inside the team's B2B campaign that holds it (9.3) | Its bid by the roles of section 2 on the B2B keyword's own evidence (9.2); for an invest, its campaign's budget and top of search too (9.5) |
| Remarketing | The product's Sponsored Display audience campaign | Not built: a later phase |

- **An AMC copy is never an owner.** Until phase 2 the copies are left as they are (section 2's kind table). Once the
  consumer owner carries the uplift, that search's copies are paused (later phases, fold design 4f).
- **A non-invest search's consumer owner is the incumbent:** the campaign holding its enabled exact keyword with the
  most clicks in 90 days, among the non-AMC, non-B2B campaigns. The planner already prices that keyword weekly. It
  matters once the uplift exists (phase 2).
- **A decision on one kind never binds the other.** A consumer search's role, invest, lock or rank experiment never
  holds the B2B keyword of the same search, and the reverse (9.4). A search can have a consumer invest (its SKC) and a
  business invest (its B2B exact keyword) at the same time.
- **The team builds the campaigns; the planner manages what is in them** (Kim, 2026-10-21). People create the AMC and
  B2B campaigns in the Ads console, because MarketplaceAdPros can't write `siteRestrictions`. The planner never creates
  a B2B campaign. It prices the B2B keywords, sets an invest campaign's budget and top of search, pauses B2B copies, adds
  negatives inside the B2B ad groups and adds a B2B exact keyword to the team's existing B2B exact campaign (9.3).

### 9.2 Business evidence and roles (roles design 4a, 4b)

**The business search records.** Alongside the consumer search records (`terms`) the planner builds one business record
per search (`business_terms` in plan.json) from the B2B campaigns' own Sponsored Products search-term rows. Every search
with a B2B search-term row or a B2B keyword gets one. The consumer records stop counting those rows: the consumer
search-term aggregates and the product's ad conversion are built from consumer campaigns only. Audience campaigns' rows
stay in the consumer aggregates until phase 2 decides their place.

- **The pool** is the product's B2B keywords' 90-day orders and clicks, shrunk toward the account's B2B conversion with
  the 10-click prior: `pool = (B2B orders + 10 × business.pool_prior_cvr) / (B2B clicks + 10)`.
  - `pool_prior_cvr` is 0.346 as of 2026-10-21: 3,353 orders on 9,685 clicks over 90 days, every Sponsored Products
    campaign with the business flag. It is refreshed by hand once a month, over the 90 days to the day before
    `pool_prior_as_of` (data-pull.md, "Monthly: the B2B pool's prior"). Kim, 2026-10-21: "lean on the b2b conversion for b2b campaigns".
  - Without the config number the planner falls back to the product's consumer ad conversion, as phase 1 did.
    `summary.business.pool_prior` says which (`source`: `config` or `product ad conversion`, with `cvr` and `as_of`).
  - Why: phase 1's prior was the product's ad conversion, mostly consumer clicks, and on thin B2B data it dominated.
    On the Oct 19 data the notebooks' pool was 15.1% under it and is 21.5% under the B2B prior; the prayer cards' 27.5%
    is 37.8%; the puzzles' 36.4% is 38.3% (logs/2026-10-21-b2b-lane-shadow.md, logs/2026-10-21-b2b-roles-shadow.md).
- **A search's business record:**
  - conversion `cvr_b = (B2B orders + 10 × pool) / (B2B clicks + 10)`, from the B2B search-term rows;
  - the market conversion is the consumer record's: the search's SQP market, shrunk toward the product's. The
    shoppers differ, the search doesn't;
  - `index_b = cvr_b ÷ market`, unknown when the search has no SQP row;
  - trusted at 10 B2B clicks or 3 B2B orders; its `index_basis` reads "Search terms (business)", or "Search terms
    (business, thin)" below that;
  - breakeven = profit per unit × `cvr_b`;
  - volume, impression share and organic share are the search's own, the same on both records. Organic purchases are
    SQP purchases less both kinds' ad orders (a B2B order is an order of the same ASIN).
- **The ladder is section 2's, run on the business record.** Negate when the relevance lists say the search is
  irrelevant; Rank when trusted, `index_b` at least 1.1, 150+ searches in 12 weeks and not already defended (the same
  impression-share and organic-share test); Defend when trusted and at least 1.1 but small or mostly organic; Hold at
  0.8 or above; Trim when trusted, below 0.8, on 15+ B2B clicks; Test with volume or an order but too few B2B clicks;
  Leave otherwise. Rank's sub-role is Invest at 3+ B2B orders, else Prove first. The record's reasons say B2B: "beats
  the market (<index>) on <clicks> of our B2B clicks", "trails the market (<index>) on <clicks> B2B clicks", "not
  enough of our B2B clicks to judge yet (<clicks>)".
  - **To know:** against an all-shopper market, a B2B keyword converting at the account's rate indexes near 2, so
    almost every trusted B2B keyword with orders is Rank. What holds the line: 10 B2B clicks (or 3 orders) for trust,
    150 searches of volume, and the lanes' proof for an automatic promotion (9.4). On the three products' Oct 19 data
    one search is Rank: the puzzles' "blank puzzles to draw on", 4 orders on 10 B2B clicks, index 3.08
    (logs/2026-10-21-b2b-roles-shadow.md).
  - **A seasonal product invests in no business search,** in any phase (spec 9b, ruling 4). A business search that
    would be Rank bids as Defend at its breakeven: "<phase>: a seasonal product invests in no business search, its breakeven bid; …".
- **A B2B keyword's own conversion** is its 90-day orders and clicks with the 10-click prior toward its search's `cvr_b`
  (an exact keyword) or the pool (phrase, broad); its breakeven is profit × that. An exact keyword takes its search's
  business role; a phrase or broad keyword is Discovery, or Negate when the search is irrelevant. Amazon's suggested
  high, read in a B2B ad group (9.7), bounds an exact bid.

| Business role | Action (the plan's words) | Bid |
|---|---|---|
| Negate | "Pause keyword (irrelevant search)" | — |
| Rank, the owner (9.3) | A `Business invest` row (below). Its keyword's action: "Invest: bid to be visible (…), top-of-search +50% (business)" or "Prove first: bid to be visible (…), top-of-search +30% (business)" | Amazon's suggested median for the search read in a B2B ad group, or breakeven if higher, never above that suggested high. No suggestion: 1.5 × breakeven |
| Rank, not the owner | "Pause here: the business owner holds this search", only while the owner invests (9.3) | — |
| Hold, Defend | "Hold at breakeven (business)" | Its breakeven |
| Trim | "Trim to 70% of breakeven (business)"; below index 0.5 on 30+ of its own clicks, "Pause: trails the market badly on 30+ clicks (business)" | 70% of breakeven (min $0.10) |
| Test, Leave, Discovery | "Hold at breakeven (business, capped at the B2B average until 3 orders)" | Its breakeven, capped at profit × the pool until it has 3 orders |

- **Every business row says what it was priced on.** The why starts "Amazon Business campaign: priced on the B2B
  campaigns' own conversion (<pool> pooled, 10-click prior), never on the consumer search." An exact keyword's names its
  search's conversion and role too: "Amazon Business campaign: priced on the B2B campaigns' own conversion (<search>
  on this search, <pool> pooled, 10-click prior), never on the consumer search. Its search's B2B role is <role>: <its
  reason>." Every business row carries `owner_kind: business`. The priced ones (a business `Bid change`, a `Business
  invest`, a business `New exact keyword`) also carry `baseline_cvr` (the pool) and `prior_cvr`; a business `Pause
  keyword`, `Negative exact`, `Stop-loss review` or `Scale Insights rules` row carries `owner_kind` only.
- **The `Business invest` row: one per owner keyword, and the whole change.** Like a consumer promotion it carries the
  bid, its campaign's budget and its top of search together. No separate `Bid change` or `Budget and top of search` row
  is written for the owner.
  - Its fields: `keyword`, `keyword_id`, `campaign_id`, `ad_group_id`, `current` (the live bid), `new` (the invest
    bid), `role` (Invest or Prove first), `tos` (the standing policy), `tos_now`, `budget`, `budget_now`,
    `other_placements` (as live), `owner_kind: business`, `modelled_spend_month`, `own_band_month`,
    `modelled_net_month`, `evidence`, and the campaign-wide `campaign_tos` and `campaign_budget` (9.5).
  - The budget is $10/day Invest or $5/day Prove first, or the campaign's live budget when that is higher: a campaign a
    person built is never lowered.
  - Its why: "<the business why> Beats the market on its own B2B clicks: index <index> on <clicks> B2B clicks, <orders>
    orders. Bid: Amazon's suggested median read in a B2B ad group, or breakeven if higher, never above the high." It
    ends with the campaign-wide sentence (9.5).
  - No row when bid, budget and top of search are already as planned: the owner is already invested as planned
    (`business_live_invests` in plan.json). It still counts in its campaign's update, the placement sweep and the
    budget steps.

### 9.3 One owner inside the business kind (roles design 4c)

Section 3 applies inside the business kind as it does for consumers, and never across kinds.

- **The owner** of a business invest search is its enabled B2B exact keyword with the most clicks in 90 days, ties to
  the lower campaign id. Enabled means not held by the live inventory, and in a campaign that serves (not paused or
  archived).
- **Its copies.** Every other B2B exact keyword of the search is paused while the owner invests. The action is "Pause
  here: the business owner holds this search", and the row's why "<the business why> The business owner (the B2B
  exact keyword with the most clicks) holds this search: one owner per search inside the business kind."
  - A copy with orders is paused too: a pause, with orders or not, is Auto (7.3; a person's call until 2026-10-22).
  - When no owner can invest (every B2B exact keyword of the search held by the inventory, or in a paused campaign), no
    copy is paused and each keeps its Hold price. The search never loses its live B2B exact coverage.
- **Funnel negatives inside the kind.** Every B2B Sponsored Products ad group that paid for the search in 90 days, other
  than the owner's campaign, gets a `Negative exact` (Auto, like every funnel negative, since decision 98; a person's call until 2026-10-22): "<the pooled business why> This B2B ad
  group paid for the search in the last 90 days; the business owner holds it from now on."
  - Section 3's two exceptions hold: never inside a B2B exact campaign, never on a close variant of a campaign's own
    exact keyword. The skipped ones are in `skipped_negatives` with `owner_kind: business`.
  - Consumer ad groups never get a negative for a business invest, and B2B ad groups never get one for a consumer
    invest.
- **A business invest search with no B2B exact keyword** (it converts for business buyers through the B2B phrase or
  broad campaigns) gets a `New exact keyword` row: a promotion for the lanes (9.4), judged on the ladder like any promotion since decision 98
  (a person's call until 2026-10-22). It goes For human only when it can't be written (no B2B campaign or ad group, 7.9).
  - It adds the exact keyword, at the invest bid and enabled, to the team's B2B exact campaign named with
    `business.exact_campaign_marker`, "B2B - Search Terms with Sales - Exact": the one already holding the most business
    owners, else the lowest-numbered. It carries the campaign update a Business invest carries (9.5).
  - Never a Launch Targets campaign: the team's Launch Targets strategy negates a search in that ad group once it has an
    order, and an invest search has orders.
  - Its `how` says to check the target ad group's negatives for the search first (live-checks.md). With no keyword row
    of that campaign read, its ad group is unknown: the row says so and carries no payload, and the preview's table says
    "no payload: ad group unknown" for its top of search and budget.
  - A marker campaign the keyword report names but `campaigns.json` lacks (the file not read, or the campaign missing
    from it) is a home too, as a campaign not read live: its id and ad group come from the keyword rows, and no budget is
    written to it (spec 9b, rulings 7 and 18).
  - With no marker campaign in either, the row says "No enabled B2B campaign named "B2B - Search Terms with Sales -
    Exact" in campaigns.json (not read, or none exists): check the Ads console before building one (MarketplaceAdPros
    cannot build an Amazon Business campaign), then the next run adds the keyword; …". It carries no payload and puts
    nothing on the checks list.
  - The controller's call, 2026-10-21 (spec 9, call 2): the team builds campaigns, the planner manages what is in
    them, so adding a keyword to an existing B2B campaign needs no console step.
- **The checks list.** Every business owner's ad group, and the ad group a new business exact keyword goes into, go on
  the plan's `checks` (self-blocking negatives before the bid goes up), as the consumer SKC ad groups do. The team's B2B
  ad groups carry Scale Insights negatives.
- **Never across kinds.** The consumer owner rules (the SKCs, the idle SKCs, the consumer duplicate pauses and funnel
  negatives) see consumer campaigns only; the rules above see B2B campaigns only.

### 9.4 Lanes, locks and invested, per shopper kind (roles design 4d)

- **Business rows take the lanes of section 7, as consumer rows do** (Kim, 2026-10-21 evening: business rows are AI
  handled, not a human row). There is no business-only lane rule:
  - cuts and pauses are automatic, with orders or on an invested search too (7.3, since 2026-10-22);
  - raises follow the evidence ladder, with no step or count (7.1, 7.4; decisions 164 and 165);
  - promotions go by the ladder; the bands and the $60 loss line are information (7.5); no money level (7.7);
  - the always-human types stay human (7.9).
  - Auto is on for every AI product since decision 98 (2026-10-22), business rows included. The shadow step and the
    Nov 9 gate they waited on are superseded (7.11).
- **The evidence is the business record.** The lanes look a business row's search up in `business_terms`, so its
  index, its orders and clicks, the market baseline, the confidence and the opportunity are the B2B keyword's own. The
  opportunity uses the search's SQP volume, as for consumers: the searches are the same, what differs is who converts.
- **The business promotions.** `Business invest` is a promotion (`lanes.PROMOTION_TYPES`), judged like `Reuse exact
  campaign`: Kim's ladder on its business record (Prove first 2 orders at index 1.1 since decision 178, 1.25 before; Invest 3 at 1.1) (the Prove first bar was 1.4
  until the config change of 2026-10-22, 7.1); its own search's band, the $60 loss line and the product's band are
  information (they parked it until decision 100, and Kim's $600 until decision 99, 2026-10-22). A business `New exact keyword` is
  judged as a promotion too (modelled spend, the bands as information, the book owner's approval level).
  - **Modelled spend.** A Business invest's is its search's B2B 90-day spend across the B2B campaigns ÷ 3, scaled by
    the bid ratio (new ÷ current), its orders scaled the same: the search's, like the consumer record's ad spend, so it
    counts the phrase groups' spend the within-kind negatives move to the owner and errs toward the caps (spec 9b,
    ruling 15). A new keyword's is `invest_per_day × 30 × business.new_keyword_spend_share` (0.25), its orders capped at
    the search's B2B 90-day orders ÷ 3 (spec 9b, ruling 11). So business invest spend counts in the search's band, the
    $60 loss line and the product's planned invest.
  - **Forecasts per kind.** The re-rank and the bands key a business row as `business:<search>`, so a business invest
    never overwrites the consumer owner's numbers of the same search. The preview's budget table labels a business row
    "B2B".
  - **The standard budget** of a business promotion is the larger of the campaign's live budget and the role's ($10
    Invest, $5 Prove first): a B2B campaign already above the standard is not odd (spec 9b, ruling 9). Any other
    budget goes to a person: "it has a budget of $<n>/day, not $<m>/day (its campaign's live budget, above the standard
    $10/day for Invest), so a person decides".
  - **One campaign, one group** (spec 9b, ruling 6). The Business invest and business New exact
    keyword rows of one campaign write one campaign update (9.5), so they are judged and approved as one group.
    - Each row is judged on its own evidence; its own search's band is information (`over_loss_line`). The group's head
      carries the group's monthly spend (`group_spend_month`) for the product's band and planned invest.
    - The group takes the weakest lane of its rows, with that row's reason: "part of the business invests of
      <campaign>: <search> needs a person: <reason>", or "… is held back: <reason>".
    - Every row of the group passes the standard budget and top-of-search check on its own row, the head's as well as
      the others'. A row with a budget override sends the group to a person, as a consumer promotion with one goes: "…:
      zebra cards needs a person: it has a budget of $25/day, not the standard $10/day for Invest, so a person decides"
      (final review, 2026-10-21). Otherwise the campaign update would write that budget on an automatic head.
    - An automatic group says "enough proof for Invest: <proof>; with the other business invests of its campaign it
      fits the product's monthly invest band ($<need> of $<left> left)", or "... it goes past the product's monthly
      invest band ($<need>, with $<left> left) (information only: no cap, decision 100)". Until 2026-10-22 a short band
      sent the group to a person ("the product's monthly invest band is short: the business invests of its campaign need
      $<need> and $<left> is left").
    - `dashboard.py approvals` sends the group whole: it is held, or goes out, together (it counted the group against
      Kim's $600 level until decision 99, 2026-10-22).
    - The Bids card shows each row's campaign-wide top of search and budget (`campaign_tos`, `campaign_budget`), what
      its campaign update writes, next to the live ones; a Prove first row riding an Invest shows +50%, not its own
      +30%. An approval is checked against the same values on the plan's row, so it never fails as re-planned (spec 9b,
      ruling 19).
  - **Bundles.** A business invest's own copy pauses and funnel negatives share its lane ("part of the promotion of
    <search>: …"), matched on the search and on `owner_kind`. They never bundle with a consumer promotion of the same
    search, and consumer rows never bundle with a business one.
- **Locks are per shopper kind.** A decision on a business row carries `owner_kind: business` into the product file's
  `decisions` (`dashboard.py approvals` and `applied` write it). The dashboard's saved reviews do not carry it, and need
  not: a review decline is keyed by row id and keyword id only. Its search-text lock is keyed
  `business:<search>`, so it holds the business rows of that search only. A consumer decision or a rank experiment
  never holds a business row, and the reverse (7.8). Row-id, keyword-id and target-id locks are specific already.
- **Invested is per kind.** `log_invest.py` records business invests (the Business invest and business New exact
  keyword rows that went out) in the product file's `business_invest_log`: the same shape as `invest_log`, plus
  `owner_kind` and the `campaign_id`, with the business record's index, clicks, orders, spend and sales as the baseline.
  - An entry started without a row (its campaign needed no change, or its owner is held, say by the visibility review)
    takes the `campaign_id` of the owner already invested as planned (`business_live_invests`), else of the search's
    business owner keyword (`business_owners` in plan.json). Its stop-loss review then has a row id of its own, apart from
    a consumer review of the same search.
  - An entry leaves only by a person's business step-down, into `business_invest_history` (9.6).
  - A cut or pause on a business row is checked against the business set (the business log and this run's business
    Rank searches): "the team is investing in this search; cuts and pauses go through the stop-loss review" (7.3).
    Consumer rows are checked against the consumer set.
- **Approval levels (7.10).** Business promotions and their bundles are the book owner's, like consumer ones (Lee's
  until 2026-10-22), whatever their monthly spend (Kim's past $600 a month until decision 99, 2026-10-22).

### 9.5 Placements and budgets (roles design 4b, 4e)

- **Top of search on the team's B2B campaigns is treated like the consumer rank campaigns'** (Kim, 2026-10-21: "for
  the team's b2b campaigns that handle top of search, treat it the same as the consumer rank campaigns").
  - A B2B campaign holding a business invest runs the standing policy (+50% Invest, +30% Prove first; section 2) for
    every keyword in it. The campaign's top of search is the highest policy among its business invests, this run's
    and those already live (+50% beats +30%); its budget is the highest among them, never lower than live.
  - Every Business invest and business New exact keyword row of the campaign carries those campaign-wide values
    (`campaign_tos`, `campaign_budget`), and its why ends with them. From the puzzles' shadow (2026-10-21): "Campaign-wide:
    top of search +50% (live +95%) for every keyword in it, the highest policy among this run's business invests in it:
    blank puzzles to draw on Invest; budget $10/day (live $10)."
  - A held placement reads "top of search held as live (+<n>%), see the placement note"; a campaign not read live,
    "budget not read live, so none is written".
  - **The first approved business invest on a B2B campaign cuts top of search for every keyword in it,** from the
    team's +95% to +105% (2026-10-21) to +50% or +30%. That is Kim's decision. The row says from what to what, and the
    preview's Business invest table shows top of search and budget from and to.
  - The payload writes the campaign update once per campaign, in `5_campaign_updates.json`: the budget and the complete
    placement list at the campaign-wide values, every other placement as live. Any subset of the campaign's rows writes
    the same update (map-playbook.md).
  - A B2B campaign with no invest keyword keeps its top of search as live, like any consumer non-invest campaign.
- **The placement sweep judges B2B campaigns like any other** (placements.md). A campaign carrying a business invest
  this run, or an invest already live (spec 9b, ruling 12), is `changing` and gets no second proposal. One with only
  Hold or Trim keywords may get a placement-economics proposal, information only: the placement policy (decision 155)
  and the placement shape (decision 140) already act on their own (Kim, 2026-10-31). The sweep leaves audience campaigns'
  boosts alone; their bidding strategy still moves to down only on its own.
- **The budget steps judge B2B campaigns** (budget-headroom.md): out of budget on 5 or more of 14 days at an ACOS at or
  under 80% of the product's breakeven ACOS earns +50%, Auto like any budget step (a person approved until 2026-10-22). Left out: this run's invest campaigns of
  both kinds (a campaign with an invest budget this run gets no second budget row) and the audience campaigns.
- **Read `siteRestrictions` back unchanged after any `sp_campaigns` update to a B2B campaign** (map-playbook.md).
  MarketplaceAdPros can't write it, and a dropped flag would open a business campaign to every shopper.
- **No `SITE_AMAZON_BUSINESS` placement modifier** on consumer campaigns. It's a separate idea, not part of the fold.

### 9.6 Stop-loss on the B2B keyword's own numbers (roles design 4f)

Nobody has published whether a business account's purchase moves keyword-level organic rank. So a business invest is
judged on what it earned, never on Rank Radar (the controller's call, 2026-10-21, spec 9, call 1; Kim did not
object).

- **When:** after 4 weeks (`stop_loss_weeks[0]`) in `business_invest_log`.
- **It has earned its keep** when both hold:
  - its B2B orders grew: orders now above `orders_then`. The 90-day windows overlap, so this is a proxy for orders
    since the start;
  - its 90-day ACOS is at or under the product's breakeven ACOS (profit ÷ price, as the budget steps compute it).
  - Without a price or unit profit, orders alone decide, and the row says so.
- **Otherwise** the run writes the step-down itself (`stop_loss.py`, decision 98). Only where no step-down can be written
  (its B2B exact keyword isn't in this run's keyword report) is there a `Stop-loss review` row, held (Monitor) for the next
  run since decision 107 (a person's call before; `owner_kind: business`; the `campaign_id` from the
  log): "Invested in the B2B campaign for <days> days: orders <then> -> <now>, ACOS <acos> against the <breakeven>
  breakeven. Step down to Hold at its breakeven; when no invest keyword is left in the campaign, top of search back to 0%
  and the budget as live, unless the user wants more time."
- **The kinds stay apart.** The consumer stop-loss (organic rank and organic purchases; section 4) never judges a
  business invest, and the business review never judges a consumer one. A harvest-mode season plans neither.
  `log_invest.py` steps a business invest down only on a business decision: an approved business stop-loss review, or
  an approved business cut or pause on the invested search. Each log's waiting set reads its own kind's rows: a
  business row waiting on a search never keeps a consumer step-down of the same search as it was, nor the reverse
  (spec 9b, ruling 13).

### 9.7 Suggested bids and Scale Insights (roles design 4h)

- **Suggested bids from a B2B ad group.** A B2B auction prices differently (B2B clicks $1.63 against $0.87 consumer, 90
  days to 2026-10-21), and the phase 1 shadow saw a consumer high cap a B2B bid below its breakeven. So business invest
  searches get their own pull: `suggested_bids_business.json`, the same shape as `suggested_bids.json`, read with
  MarketplaceAdPros `get_amazon_ads_ad_group_bid_recs` in the owner's B2B ad group (data-pull.md). A consumer suggestion
  never stands in for a business one.
  - A business invest search missing from it stops the run with exit 2 and `need_suggested_bids_business.json`, which
    names each search with a B2B campaign and ad group to read it in: the owner's, else the ad group its new exact
    keyword goes into, else the B2B ad group that paid most for it. Its how says to read it "in the named B2B ad group,
    or any enabled B2B ad group of the product when none is named", as the consumer file names any enabled ad group.
    The planner prints "<n> business invest searches need Amazon suggested bids from their B2B ad group first: see
    need_suggested_bids_business.json".
  - Only the searches a row will price are asked for: an owner that can invest, or a new exact keyword.
  - Once Amazon was tried (`bid_sources_tried.json`; decision 106, 2026-10-23) the run no longer stops: a business
    invest search still without a suggestion takes the no-suggestion bid, 1.5 × its B2B breakeven, and is listed in
    `summary.bid_fallback.business_searches`. SoldScope has no B2B figure, and a consumer one never stands in.
  - A search the file lists with no median falls back to 1.5 × breakeven.
- **Scale Insights: the B2B ad groups come off the team's bid rules** (SKILL.md rule 1, one bid owner per product). A
  B2B ad group the planner prices can't stay on Scale Insights bid rules: the nightly rules would move the bids back
  within a day, and the Launch Targets strategy negates the very searches that convert.
  - Every run of a product with B2B campaigns (archived ones left out) carries one `Scale Insights rules` row, keyword
    "B2B ad groups", `owner_kind: business`. It is the standard Scale Insights setup, so Auto since decision 98, done in the
    signed-in browser and read back (a person's call until 2026-10-22: the book owner's, Lee's before). The B2B campaigns are `campaigns.json`'s and those the keyword report names that it lacks, with their
    ids from either source, so a campaign list not read never hides the row (spec 9b, ruling 18):
    - change: "Take the bid rules off the Amazon Business (B2B) ad groups of this product";
    - now: "The team's B2B strategies (inch-up and target-ACOS rules; Launch Targets negates searches with orders)";
    - after: "Strategy 103 / 302497 for the exact campaigns that own a business invest search (<campaigns>), with those
      searches whitelisted (<searches>); strategy 101 / 302489 for the other B2B ad groups (<campaigns>)". With no
      business invest this run it reads "Strategy 101 / 302489 for the B2B ad groups (<campaigns>)";
    - why: "Scale Insights bid rules run every evening and would move the AI's business bids back within a day; the
      Launch Targets rule would negate the searches that convert.";
    - how: "Scale Insights web app (references/scale-insights-playbook.md); then set business.si_rules_off to the date
      and add <campaign ids> to business.si_exact_owners in the product file" (the ids of the campaigns it moves to
      103; with none, only the date). The playbook's recipe "Assign a strategy to many ad groups" does it.
  - **Every run carries the row until the product file's `business.si_rules_off` holds the date it was done.** A decline
    locks it like any row: Kim can keep any product's B2B ad groups on the team's rules by declining it.
  - **A campaign that newly holds a business invest after that still moves to 103** (spec 9b, ruling 17). The product
    file's `business.si_exact_owners` lists the campaign ids already on the exact-owners strategy with their searches
    whitelisted. While a campaign holding a business invest this run (a row, or an invest already live) is not on it,
    the row comes back, naming only those campaigns and their searches:
    - change: "Move the B2B campaigns that newly hold a business invest to the exact-owners strategy";
    - now: "The B2B bid rules came off on <date>; these campaigns are not in business.si_exact_owners, so they still run
      the team's B2B strategy";
    - after: "Strategy 103 / 302497 for the exact campaigns that newly own a business invest search (<campaigns>), with
      those searches whitelisted (<searches>)";
    - how: "Scale Insights web app (references/scale-insights-playbook.md); then add <campaign ids> to
      business.si_exact_owners in the product file".
  - Take an ad group off those rules before an approved business bid goes out, or Scale Insights moves the bid back.
  - This ends the interim of 2026-10-21 morning, when the team put the B2B ad groups back on their Scale Insights B2B
    strategies until the fold shipped (docs/b2b-scale-insights-reassignment-2026-10-21.md). The controller's call
    (spec 9, call 8), following from Kim's "AI handled" and the one-owner rule. The rows go out only when a person
    approves them, product by product.
- **The blacklist rescue** (section 3) takes business invest searches off the product's blacklist as it does consumer
  ones: the searches in the business invest log and this run's business Rank searches.

### 9.8 What stays from phase 1, and what isn't covered

- **Stays:** the classifier and the Business family; Hold, Trim and Pause on the keyword's own index; the suggested high
  bounding an exact bid; `owner_kind` on every business row and in the published change rows (the dashboard's `b2b`
  scope lever counts only those rows).
- **Never a duplicate across kinds, in Sponsored Products or in Sponsored Brands video** (section 3):
  - a B2B keyword is never paused as the consumer SKC's copy and never moved into a consumer SKC;
  - a B2B ad group never gets the consumer owner's funnel negative;
  - a "Videos - B2B" keyword is never paused as an older SB copy, and its campaign never counts as the AI's video
    series. Sponsored Brands B2B video keywords aren't priced: they stay as live;
  - every B2B campaign of the three products that have them carries the flag: puzzles B0SAMP0016, gold-foil notebooks
    B0SAMP0013 and prayer cards B0SAMP0017, all 56 checked 2026-10-21 (28 SP, 28 SB). An SB campaign read that comes
    without `siteRestrictions` still classifies by the name marker.
- **The visibility review's business exclusion stays:** a B2B row is not eligible for a consumer delivery rescue.
- **The negative-keyword audit stays as it is** (Kim, 2026-10-21: "the current negative audit skill is fine"). It
  still judges search terms in B2B ad groups on consumer thresholds. Its rows are always a person's call, and the
  approver treats a row in a B2B ad group as business.
- **An invest search with no B2B campaign at all.** When the product has a B2B offer but no B2B-exclusive campaign
  holds the search, a person builds one in the Ads console. The planner's Needs-human item for it is phase 2.
- **The plan summary's `business` block** counts what the run saw: `campaigns`, `keywords`, `pooled_cvr`, `pool_prior`
  (`cvr`, `as_of`, `source`), `bid_changes`, `pauses`, `invest`, `prove_first`, `copies_paused`, `negatives`,
  `new_keywords`, and (spec 9b, ruling 14) `stop_loss_reviews` and `si_rows`, the business `Stop-loss review` and
  `Scale Insights rules` rows. The shadows: logs/2026-10-21-b2b-lane-shadow.md (phase 1) and logs/2026-10-21-b2b-roles-shadow.md
  (business roles and lanes).

## 10. Data stages (built 2026-10-22; design `docs/superpowers/specs/2026-10-21-keyword-selection-by-data-stage-design.md`)

Sections 1 to 9 read every product's SQP the same way. A product with three weeks of SQP is not a product with twelve: the
gel pens (B0SAMP0012) had 21 observed days on the SQP through 2026-10-17, and that third week more than doubled the
product's clicks and took its purchases from 3 to 54 (measured 2026-10-22 on the three SQP pages through Oct 17; the
design's 50 was an estimate from page 1). This section says how much each stage of a product's data may decide. The
code is `scripts/stage.py` (the stage and its small checks), `plan.py` (the roles) and `lanes.py` and `plan_lanes.py`
(who has to say yes). Kim's answers of 2026-10-21 are cited where they set a number. The numbers are in
`config.json` (`stage`, `fallback`, `discovery`, `launch`, `thresholds` and `auto.prove_index`; the full-window line is
`stage.full_window_days` since 2026-10-22), except two windows fixed in `scripts/stage.py`: 84 days, the planner's own
full window (what a row with no observed-day count, or a product without SQP, is read as), and 90 days, how long a
launch block counts.

### 10.1 The three stages

| Stage | How a product gets there | What the planner does |
|---|---|---|
| **launch** | The product file has a `launch` block whose `date` is within 90 days, **and** SQP has fewer than `launch.sqp_min_queries` (10) queries with impressions | Nothing yet: `plan.py` stops with the launch-stage message (10.7). The team's own launch structure carries the first weeks. The launch plan's Task 3 will plan launch mode from this stage |
| **early** | Not launch, and not recorded mature (below), and SQP's longest observed-day count is under `stage.full_window_days` (77; below), **and** that count is under `stage.early_max_observed_days` (28) **or** fewer than `stage.early_min_trusted_queries` (5) queries carry `thresholds.trusted_min_clicks` (10) or more of our clicks | Today's roles and bids, with the five differences of 10.3 |
| **mature** | Everything else, and any product whose file records `data_stage: "mature"` | Today's rules, with the few exceptions in 10.5 |

- **Observed days** are the longest `QueryObservedDayCount` across the run's SQP rows (a row with no count is read as a full
  84-day window; no rows reads 0). **Trusted queries** are the rows with 10 or more of our clicks. The stage is the
  product's, not the search's.
- **The full-window line: 77 days** (`stage.full_window_days`; corrected 2026-10-22 at build time from the design's
  84). A product whose SQP holds the full window is mature whatever its traffic, so the old low-traffic listings stay
  mature and the early rules touch recent launches only. The design said 84 days, SQP's full 12 weeks, but a 90-day
  Scale Insights pull holds at most 11 complete weeks: the longest `QueryObservedDayCount` on the team's saved pages is
  77 (B0SAMP0001, 602 rows, counts 49/56/63/70/77), so an 84-day line never fired, and the three old listings the design
  named (B0SAMP0007, B0SAMP0018 and B0SAMP0019, on the SQP saved on 2026-10-21) would have planned as early. 77 was set
  on 2026-10-22 and confirmed by Kim the same day (decision 93, open item 42 closed); a config without the key keeps 84. B0SAMP0018 (AI-owned, launched 2025-12-19, 2 trusted
  queries) carries `data_stage: "mature"` by hand since 2026-10-22, the record of 10.6 winning whatever its SQP;
  B0SAMP0019 and B0SAMP0007 have no product file in this repo yet.
- **28 days and 5 trusted queries** are design calls, made 2026-10-21 and kept in config: 28 days is four SQP weeks, where
  the gel pens' head terms stopped changing verdict from week to week.
- **A product with SQP and no `launch` block is early, never launch.** That is the gel pens today and every product
  onboarded before this section: launch needs the block's list to plan from, and nothing writes a block after the fact.
  A launch block older than 90 days does not make a product launch either.
- **Mature sticks.** A recorded `data_stage: "mature"` wins over every other test. A stock-out thins SQP; it does not make
  a product new again. `dashboard.py refresh --asin <ASIN> --run <run>` records the stage (10.6). To re-stage a product,
  a person deletes the `data_stage` line from its product file and says why in the run log.
- **Leaving a stage.** A product leaves launch on the first run that sees 10 queries with impressions
  (`summary.stage.left_launch_this_run` is true when the file still records launch and has a launch block, and this run
  is not launch; nothing records launch until the launch plan's Task 3 plans launch-stage runs, so today it is always
  false). It leaves early on the first run whose SQP satisfies both counts, and the run log says so ("stage early -> mature: 28 observed days, 13 trusted
  queries"). The gel pens: early on the SQP through 2026-10-17 (21 observed days, 13 trusted queries); mature on the SQP
  through 2026-10-24 if 5 or more queries still carry 10+ of our clicks.
- **Seasonal products** (section 8) are planned by their season block whatever the stage, and are never stopped at the
  launch exit. The stage is still computed and reported.
- **Where the stage shows.**
  - `summary.stage` in plan.json: `{stage, sqp_queries, observed_days, trusted_queries, reason, left_launch_this_run}`.
  - `stage`, `volume_basis`, `relevance_flag`, `fallback_index` and `sqp_observed_days` on every term row, and as columns of
    terms.csv.
  - One note per product in the preview when the stage is not mature ("data stage early (21 observed days, 13 trusted
    queries, 231 SQP queries with impressions)", with the volatile-week text after it when there is one).
  - The run log's stage line, `stage: early (21 observed days, 13 trusted queries)` (weekly-run.md, step 14.3).

### 10.2 The source ladder: what each input may decide

| Source (where the skill reads it) | What it tells us | The most it may support | Stage |
|---|---|---|---|
| SQP, same query: our clicks and purchases against the market's (Scale Insights `get_search_query_data`, `sqp_p*.json`) | Conversion against the market, volume, impression share, organic share | Invest, and every other role | early, mature |
| Search-term report (`st_p*.json`) against the **product's** market conversion | Our ads convert this search; there is no same-query market | **Prove first** (10.3, item 2). The report still prices a Test and feeds the negation as before. Never Invest, Hold, Trim or a raise | early only |
| DataDive niche keyword list (`get_niche_keywords` on the Monday "1st Datadive" niche, saved as `niche_keywords.json`) | Monthly volume, relevancy (the share of the niche's competitors ranking), competitor ranks | The launch list and its order (10.7); the launch list's volume is the volume of a search SQP has not shown; the niche list is what the 'unlisted' flag checks against | launch, early |
| Amazon's keyword recommendations (MarketplaceAdPros `get_amazon_ads_ad_group_keyword_recs` on the harvest ad group, saved as `keyword_recs.json`) | Amazon's own candidates, with impression rank | The launch list's `amazon` tail, after the niche's own list. Never a promotion | launch, early |
| SoldScope monthly volume (`soldscope_volume.json`, from `common_search_volume_batch`) | Volume for any search | The volume of a search that neither SQP nor the launch list has: it feeds the 150-search gate, the opportunity ordering and the bands | all |
| Amazon's suggested bids per ad group (`get_amazon_ads_ad_group_bid_recs`, `suggested_bids.json`) | Low, median and high for a keyword in its ad group | The bid of every Invest and Prove first search (unchanged) | all |
| DataDive Rank Radar (`get_rank_radar_data`) | Organic and sponsored position per day | The outcome of a rank build: the stop-loss reads its 7-day median (unchanged). **Not a role input**: on 2026-10-21, 3 of the gel pens' 30 tracked searches touched the top 10 on single days and were off page 1 the next, so a radar-fed Defend would need a definition of "defended" that survives that noise | mature (stop-loss) |
| The product's relevance lists and roots (`relevance.*`, the `launch` block's `roots`) | What the product is not, and what every relevant search contains | Negate, and the two flags (10.3, item 4) | all |

The order is the order of trust. A source lower in the table never overrides a verdict a higher one has given on the same
search: once SQP has a market for a query, the search-term fallback no longer applies to it, and the launch list and
SoldScope only ever supply a volume.

### 10.3 The early stage's five differences

Everything else in early is today's planner: Test at the provisional breakeven, Hold and Trim from the trusted same-query
index, the harvest campaign and its gates, the negation audit, the stop-loss and the Day-1 check. Items 4 and 5 are
written here because they came with this build, but they apply at every stage.

**1. A promotion in early is Auto only when three things hold** (Kim, 2026-10-21 evening: the more obvious candidates
like "gel pens for coloring" decided by the AI, the flagged terms like "pen" and "school supplies" left to a person). A
promotion is a New or Reuse exact campaign, or a live rank campaign's policy-only top-of-search row (7.5), on a consumer
Invest or Prove first search. It can be Auto only when (a) its search carries no head-term flag (item 4), (b) its SQP row
has at least `stage.auto_min_observed_days` (14) observed days, so it has been seen in two SQP weeks and not one (at every
stage since 2026-10-25, decision 135; a search with no SQP row is not counted here), and (c)
the run is not a volatile week (10.4; early only). A row that fails (a) goes to a person, with the reason named:
a promotion at the book owner's level (Lee's until 2026-10-22; Kim's when past his $600 a month until decision 99,
2026-10-22: two of the gel pens dry run's four promotions were past that line); a policy-only top-of-search row at the
owner's level (7.5, 7.10). A row that fails
(b) or (c) is held (Monitor) since autonomous runs (2026-10-22): its second SQP week, or a steadier week, settles it, so
it is not a person's call; it went to Needs human before. The check runs after the lock, stale-data, onboarding,
season-switch and cut rules of 7.2 and
before the ladder, so a cut is never held by it, and a business row (section 9) is judged as before. For the second
condition the reason reads "early SQP: seen in one SQP week only (<days> observed days, under 14), so it waits for its
second week" (until 2026-10-22: "so a person decides until its second week"). The ladder and the standing top-of-search
policy apply as today (the bands are information since decision 100, and there is no money level since decision 99). Since 2026-10-22 Auto is on for every AI product (decision 98; the Nov 9
gate of 7.11 is superseded), and an onboarding product's rows are judged like any other's (7.9).

**2. The search-term fallback may reach Prove first.** For a consumer search with no same-query market (no SQP row, or one
with no market clicks), in stage early only, the planner computes `fallback_index`: the search's ad conversion, shrunk
toward the product's market conversion with the 10-click prior, divided by the product's market conversion (the
click-weighted SQP market conversion of the product). A search qualifies when it has `fallback.min_clicks` (5) ad clicks,
`fallback.prove_orders` (2) ad orders and a fallback index of `fallback.prove_index` (1.1 since decision 178; 1.25 before) or more, and its volume
(item 3) reaches `thresholds.invest_min_volume` (150). The 5-click floor is Kim's, 2026-10-21 ("5 click floor totally
makes sense. bake it in"): 2 orders on 2 clicks proves nothing, and 5 clicks makes the row mean something. The row reads
`index_basis: 'Search terms vs product market'`, `index_status: 'product_market_fallback'`, `sub_role: 'Prove first'`,
`index: None` and `fallback_index` set, and its Why reads "no SQP row yet; its ads convert 1.51x the product's market (2
orders on 7 clicks, 10-click prior): Prove first on the search-term fallback". The value lives in its own field so that
nothing else can read it as an index: the raise lane, the opportunity ordering and the market review read `index`, which
is `None`. It supports exactly one promotion, Prove first; never Invest, never Hold or Trim, never a raise. The lanes hold
it as follows, at every stage, since 2026-10-23 (decision 107): a promotion on a fallback term is Auto, a small Prove-first
test the stop-loss ends if it doesn't pay ("Prove first on the search-term fallback (no SQP row yet): its ads convert
<x>x the product's market; ..."), and a raise on its live keyword is Monitor ("... its live keyword keeps its bid, since
the fallback supports a Prove-first test in its own exact campaign and never a raise"). Both were Needs human until then. An approved fallback Prove first is written to the invest log like any promotion. A logged Prove first
whose search still has no same-query index stays a rank term ("in the invest log as Prove first since <date> and SQP shows
no same-query market yet: kept a rank term until its stop-loss review, never re-cut as a Test"), after the product turns
mature too, until the stop-loss closes it. The moment SQP has the query, the same-query index takes over and the ladder
decides whether the Prove first survives: 3 orders at 1.1 is Invest, about 30 clicks with no order is Trim (section 2).
This is how section 1's rule ("a product-level prior is not a same-query benchmark") and the 2-orders promotion fit
together: the fallback is not a benchmark, so it buys the smallest promotion only. On the gel pens' probe plan of
2026-10-22 (a scratch copy of the product file), "fine point gel pen" (7 ad clicks, 2 orders, fallback index 1.51, SoldScope
519 a month = 363 in 21 days) was the one fallback Prove first, and "colored gel pens fine tip" (3 orders on 6 clicks)
stayed a Test because SoldScope has no volume for it.

**3. Volume from the next source down.** A search's volume (`volume_of` in `scripts/stage.py`) is, in this order: SQP's
`QueryVolume` as it stands, when the query has a row with one; else the launch list's monthly `volume`; else SoldScope's
monthly figure (`soldscope_volume.json`); else 0. SQP's volume covers the query's observed days (7 to 84), so a monthly
figure from the launch list or SoldScope is scaled to the product's window first: `monthly x window_days / 30`, where
`window_days` is the product's longest observed day count (84 when it has no SQP). For the gel pens (21 days),
SoldScope's 519 a month reads as 363, next to SQP volumes counted over the same three weeks. The 150-search gate and the
opportunity ordering read the result. Each row says where its volume came from, in `volume_basis` ("SQP", "launch list",
"SoldScope" or "none"), and its evidence text says it: "363 searches in 21 days (SoldScope, scaled from a monthly figure)"
where an SQP volume reads "searches in 12 weeks". The bands keep pricing from SoldScope when SQP has no clicks, as before.
In mature the same function runs, but a promotion needs its SQP row, so the basis there is normally SQP.

**4. Head-term flags send a Rank candidate to a person, at every stage** (Kim, 2026-10-21: "pen" and "school
supplies" are generic and broad and would be very hard to rank on). `relevance_flag` is `'one token'` for a one-word
search, and `'unlisted'` for a search that is in none of the product's lists: the launch list, the niche list
(`niche_keywords.json` in the run) and the roots (the `launch` block's `roots`, else `relevance.roots`; a search holding
one of them is listed, and a root matches its plural and singular, so "fine point gel pen" is listed under the root
`pens`, the same fold `launch_list.py` uses to propose roots, since 2026-10-22; a listed search's folded variants, the
launch block's `folded`, are listed too). The 'unlisted' flag applies only when the product has something to be
unlisted from, a launch list, a `niche_keywords.json` in the run or roots (decided 2026-10-22: without it every
promotion of every product onboarded before this section would go to a person); the one-token flag always applies. A
Rank row's evidence text ends
with `basis: ...; volume: ...` and, when flagged, `; flag: one token` or `; flag: unlisted` (needs-human.md). A promotion
on a flagged search is Needs human at every stage, with the reason "one-word search: a head term, generic and hard to
rank on, so a person decides (rulebook section 10)" or "not in the product's niche list, its launch list or its roots, so
a person decides whether it is the product's search (rulebook section 10)". Cuts, Hold and Test rows carry the flag as
information only. A person's yes on a flagged search is a lock like any other decision (7.8): for 4 weeks the next run
does not ask again.

**5. The Discovery cap lifts at 2 orders** (Kim, 2026-10-21: "discovery keywords with 2 orders and above should lift the
cap to its own breakeven"). A broad, phrase or auto keyword bids its own breakeven, capped at the product's average
breakeven click until it has 3 orders. It now bids its own breakeven, uncapped, from `discovery.cap_lift_orders` (2) orders
when its keyword index against the product's ad conversion is `discovery.cap_lift_index` (1.1 since decision 178; 1.25 before) or more; the action then
reads "Discovery: bid to breakeven (cap lifted: <n> orders at index <x>)", and the Bid change row says so itself (since
2026-10-22: its `why` ends "Cap lifted here: <n> orders at index <x> against the product's ad conversion, so it bids its
own breakeven" and it carries `cap_lifted`), so the preview, the dashboard and the log name why a $0.19 cap became
$0.54. This applies at every stage: it is the same
evidence bar as Prove first. On the gel pens' Oct 17 run, the "pens colored" phrase keyword (8 clicks, 2 orders) would have
held about $0.42 instead of falling from $1.15 to $0.19.

**The 2-order bar is 1.1 everywhere it appears** (Kim, 2026-10-31, decision 178; 1.25 from 2026-10-21): the Prove first
ladder (`auto.prove_index`, was 1.4 before 2026-10-22; 7.1), the fallback (`fallback.prove_index`) and the Discovery cap
lift (`discovery.cap_lift_index`). The 3-order bars
stay: Invest at 1.1 and a raise outside Invest at 1.4.

### 10.4 The volatile week

When this run's SQP adds more of our clicks than `stage.volatile_week_ratio` (1.0) times all the weeks before it, the week
is volatile, at any stage; the hold below applies in stage early only. On the gel pens' probe plan of 2026-10-22 the week
through 2026-10-17 added 389 of our clicks on top of the 214 recorded through 2026-10-10. The planner compares the run's
SQP totals (our clicks summed over every SQP row, `<run>/sqp_totals.json`) with the newest entry of the product file's
`sqp_history` (10.6). The week is volatile when the run's SQP runs through a later date than that entry, the entry has
clicks, and the run's clicks less the entry's are more than the ratio times the entry's. `summary.volatile_week` then
carries the text ("volatile SQP week: the SQP since <the entry's date> (through <this run's date>) added <n> of our
clicks, more than the <n> of all earlier weeks"; the span is named because a history that missed a week compares two
weeks against its entry) and the run log says "volatile week", at every stage. **In stage early every promotion is held** (Monitor since
2026-10-22, "...; promotions wait for a steadier week (a person may lift the hold with --allow-volatile)"; it went to
Needs human before) with that text as its reason, unless an earlier rule (the fallback, a head flag) already sends the row
to a person with its own reason (10.3; the reason is the first rule that holds the row: the fallback, then a head flag, then the
volatile week, then the two-week test); the rows are still planned and previewed. Cuts and Test re-prices are not held.
A product with no `sqp_history` has no baseline, so no hold: `dashboard.py refresh --run` starts the history from the
first run after
this section shipped, and a person may seed an older entry from a saved run folder (the gel pens' run of 2026-10-19 holds
the totals through 2026-10-10: `{"data_through": "2026-10-10", "our_clicks": 214, "our_purchases": 3, "queries": 159}`).
**The hold is early-stage only** (2026-10-22; spec 4.6 says "In early" and 4.5 leaves mature unchanged): a mature product
whose SQP doubled in a week has the text on its summary (`summary.volatile_week`), and its promotions are judged by
sections 1 to 9, not held.

**`--allow-volatile`.** A person who has looked at the week and judges it real runs `plan.py --allow-volatile`. The hold
is lifted: `summary.volatile_week` is empty, the text moves to `summary.volatile_week_overridden`, and the run log says the
hold was lifted and why. It costs one week on a product whose data is still arriving; it saves launching on a week that
turns out to be the outlier.

### 10.5 What stays the same in mature

The roles, the bids, the ladder, the bands and caps, the lanes, the stop-loss and the negation audit are sections 1 to 9
as they stand. What a mature product does show:
- `summary.stage` and `stage` on every row, and `volume_basis` (normally "SQP");
- the changes that apply at every stage: the head-term flags (a flagged Rank candidate goes to a person), the Discovery
  cap lift at 2 orders, Prove first at 1.1 (7.1; 1.25 until decision 178) and the volume ladder (10.3, item 3: a search with no SQP volume takes
  the launch list's or SoldScope's, so on a mature product it can turn a Leave into a Test);
- the volatile-week text on the summary, when the product file has an `sqp_history` baseline (10.4); it is reported only.

What mature does not get: the fallback Prove first, the volatile-week hold and the launch exit. The "seen in one SQP week
only" check applies in mature too since 2026-10-25 (decision 135).

### 10.6 The product file: `sqp_history`, `data_stage`, `launch`, `relevance.roots`

- **`sqp_history`:** a list of `{data_through, our_clicks, our_purchases, queries}`, newest last, the last 26 kept. It is
  the baseline of 10.4. `plan.py` writes `<run>/sqp_totals.json` (the run's totals and their `data_through`) and nothing
  in the product file.
- **`data_stage`:** the stage the last `refresh --run` recorded. The planner reads back "mature" (it decides the stage, 10.1)
  and "launch" (it lets the run say it left launch; nothing records launch until the launch plan's Task 3 plans
  launch-stage runs, because a launch-stage run stops before plan.json is written); "early" is information.
- **`dashboard.py refresh --asin <ASIN> --run <run>`** records both in the product file, then republishes the page. It
  appends the run's totals to `sqp_history` when their `data_through` is newer than the newest entry (refreshing twice
  adds nothing), and sets `data_stage` to the run's stage; a recorded "mature" never goes back to "early" or "launch". It
  refuses a run folder whose plan is for another product, and it refuses `--run` on a lined-up product (no run to
  record). `--dry-run` prints what would be recorded and writes nothing. `refresh` without `--run` records nothing. After
  a live refresh, **commit and push the product file**, as after any publish (weekly-run.md, step 14.5).
- **`launch`:** the block `launch_list.py` builds (10.7), pasted in at onboarding once a person has set its `date` and
  confirmed its `roots`.
- **`relevance.roots`:** the words every relevant search of the product contains, for the 'unlisted' flag (10.3, item 4)
  when the product has no `launch` block with roots. Nothing else reads them.

### 10.7 The launch list

`scripts/launch_list.py` builds the `launch` block from the product's DataDive niche, Amazon's keyword recommendations and
the research sheet's extra searches: the order is volume x relevancy, close variants fold into the higher-scoring
spelling, a search under `launch.min_relevancy` (0.5) is left out, the median set is the first `launch.rank_count` (5)
with two or more tokens (one-word heads stay in the shared set), Amazon's top `launch.amazon_top_rank` (20) additions join
at `amazon` and never re-add a search the niche left out, and the roots are proposed from the 0.9-relevancy rows for a
person to confirm. The steps, the options and the gel pens worked through are in data-pull.md, "Launch list
(2026-10-22)". `launch.placeholder_bid` and `launch.stop_loss_weeks` are for the launch plan's Task 3 and nothing reads
them yet.

A product in the launch stage is not planned yet: `plan.py` exits with "<ASIN> is in the launch stage (<n> SQP queries
with impressions, under 10): build the launch list with scripts/launch_list.py; the planner takes the product over at 10
queries". The team's launch structure, built by hand as before, carries the first weeks. The launch plan's Task 3
replaces that exit with the day-0 structure, and its `launch_state` (in `plan.py`) is a view of this stage, so the two
never disagree about the 10-query line.

### 10.8 The listing pass handed to Growth (added 2026-10-22)

The data a stage collects also says when a product's listing copy should change. From 2026-10-22 the weekly run turns
that into one paste-ready block for the Growth team, the For Growth item: the funded (Invest or Prove first) searches the
copy does not carry, the carried terms that are irrelevant or fail the pass bar, and the searches that are an offer
problem. It reads the same stage, roles and index as this section and sections 1 and 2, adds no bid rule and writes
nothing to Amazon. The first block is due 56 days after the product's anchor (the later of the Monday launch date and its
first ad click); later blocks wait at least 8 and at most 26 weeks after the last listing change, earlier only when the
evidence gate opens, and a rotate-out flag can raise one at any time outside the 30 quiet days. The bars (17 SQP clicks
and an index under 0.8 for a move-down; 30 clicks and no purchases, or an index under 0.5, for a flag), the dates and
the config keys are in [for-growth.md](for-growth.md) and `config.json` `growth`. They are not part of the bid ladder,
and a change to them is Kim's.
