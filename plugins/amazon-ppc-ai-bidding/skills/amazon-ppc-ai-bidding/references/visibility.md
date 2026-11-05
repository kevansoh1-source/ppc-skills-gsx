# Delivery-aware bidding review

Added 2026-10-19 SGT, at Kim's request. This guide is the shared handoff for Claude, Codex and the PPC team.
The engine improvement is approved; **each concrete live experiment still needs its own preview and approval**.
Nothing here launches an agent, schedules a follow-up or grants a new bid, budget, schedule or loss allowance.

## What this fixes

A sensible economic bid can leave a keyword untested if it cannot obtain traffic. Amazon's suggested low is not
a guarantee of traffic, and suggested median/high is not a profitability target. The run now keeps both views:

1. **Economic baseline:** the existing role-based bid and the evidence behind it.
2. **Delivery review:** is the target actually getting a fair test, and if not, why?
3. **Separate proposal:** only where appropriate, a finite visibility experiment with explicit limits.

Do not replace every economic bid with `max(breakeven, suggested_low)`. A low bid may already buy sufficient
qualified traffic; a Trim target may correctly lose traffic; a scheduled, blocked or low-demand keyword may not
benefit from a higher bid at all. Paid CPC, submitted base bid and effective placement/dynamic bid are different.

## Evidence and roles

- A market-relative IDX needs a usable **same-query** benchmark and sufficient own evidence. Preserve the existing
  role boundaries: IDX >= 1.1 supports Invest/Prove first or Defend according to relevance, volume and organic
  coverage; IDX < 0.8 supports Trim with sufficient data. Exactly 0.8 is not Trim; exactly 1.1 is not Hold when the
  stronger role's other gates pass. Do not round the displayed IDX before testing the threshold.
- Missing same-query benchmark means **IDX unknown**. A product-average conversion prior may estimate a provisional
  bid; it must not manufacture a claim that this query beats or trails its market. Display actual clicks/orders,
  observed and smoothed conversion, and its own economics. A broad keyword's aggregate results are not a same-query
  benchmark for every shopper query it matched.
  Missing query-market clicks or purchase counts are not zero. **Explicit zero purchases with positive market
  clicks is observed evidence** and can be smoothed using the existing prior; zero market clicks or an absent
  purchase count cannot establish the benchmark.
- **Test:** diagnose delivery after seven verified eligible days. A 14-day test is the default proposal window,
  not an automatic launch or renewal. Supply the target's evidence goal and concrete bounds before approval.
- **Discovery:** review the actual successful shopper query and propose isolated exact validation when appropriate.
  Do not lift the whole broad/phrase target to buy unrelated searches. An exception for a specific broad/phrase
  target requires the documented `query_mix_review` below, in addition to all experiment limits and approval.
  Auto groups are not priced by this module.
- **Hold / Defend:** preserve satisfactory economic delivery. Recovery needs meaningful lost coverage and a review of
  organic coverage/demand, not a universal impression quota. Any beyond-economics allowance is explicit.
- **Trim:** no automatic suggested-low rescue. Reduced delivery is often intended. New evidence or a meaningful
  offer, relevance or seasonal change is needed before proposing a fresh test.
- **Invest / Prove first:** retain existing approved experiments, placements, loss allowances and original clocks.
  Delivery diagnostics do not cancel a rank experiment or reset its stop-loss. A modeled loss allowance is not a
  spending cap. Keep the approved record and verification status separate from the new proposal.
  The evaluator returns `rank_review` for under-delivering rank roles rather than creating a replacement 14-day
  trial. Healthy rank traffic with a missing contextual range also returns `rank_review` pending verification.

The existing Oct 19 product-target rules are unchanged. Product targets use the product's own ad conversion rather
than keyword-market IDX. Their campaign exclusions and pause rules still apply. This version's contextual
recommendation/delivery contract covers **SP keywords with exact, phrase or broad match**, not SB/SD targets, auto
groups or independent SB bid recommendations. Do not translate an SP keyword recommendation into another ad type.

## Diagnose the right problem

| Evidence | Interpretation and next action |
|---|---|
| Missing inventory, report, eligibility or dated recommendations | Request the missing data; do not invent zero activity or a bid increase |
| Verified scheduled OFF period | Continue normal economic base-bid pricing. Preserve the schedule and paused state; do not infer low delivery or start a visibility test from OFF hours |
| Manual/unknown pause, paused campaign/keyword, ineligible/out of stock, budget unavailable, negative or routing conflict | Resolve the specific blocker; a bid increase does not solve it |
| Verified low query demand | Set an attainable goal, wait for a relevant season or deprioritize; bids cannot create searches |
| Enough impressions but weak click-through | Review relevance, offer, creative and placement context; avoid blindly buying more of the same traffic |
| Enough clicks but weak conversion | Review conversion/economics or use existing Trim rules; additional visibility can accelerate loss |
| Healthy qualified-click pace | Keep the economics-based approach even below suggested low |
| Eligible, relevant, meaningful demand, inadequate qualified-click pace | Consider a bounded visibility test after the checks below |

The engine uses the supplied, evidence-backed click goal and goal period rather than imposing one traffic minimum
on every search. Do not supply a convenient goal simply to trigger a bid increase. Impressions alone do not prove a
fair conversion test, and three orders alone do not remove uncertainty. Keep attribution maturity explicit.

## Reproducible input contract

Save `<run>/visibility_inputs.json` as an object containing:

```json
{
  "asin": "<the one ASIN for this run>",
  "inventory_complete": false,
  "inventory": [],
  "delivery": [],
  "recommendations": [],
  "experiments": []
}
```

This empty example deliberately represents **missing evidence**, not an executable recommendation. The agent
collects live reads described in [data-pull.md](data-pull.md); the planner does not fetch them. Retain the raw tool
responses and normalization notes in the same run folder. A reported value is not verified merely because it is
present in this JSON.

### Identity on every row

Every inventory, delivery, recommendation and experiment record repeats the complete identity:
`asin`, `keyword_id`, `campaign_id`, `ad_group_id`, `keyword`, `match`. Use string IDs, the real positive keyword text
and its actual `exact`, `phrase` or `broad` match. Text/match casing and whitespace can be normalized; IDs and ASIN
must agree. There is **no text-only join**, no cross-ASIN fallback and no exact-to-broad fallback. Duplicate or
conflicting identities must be corrected, not silently collapsed.

Set `ad_product` to `SP` for supported inventory. A contextual recommendation belongs to the specific target and
bidding strategy; it does not inherit from the legacy `suggested_bids.json` query dictionary. That dictionary
remains available to historical rank/harvest pricing, explicitly distinct from complete recommendation coverage.
If the top-level object supplies `profile_id`, repeat it on inventory and recommendation records; the matcher
requires agreement. Never combine profiles or marketplaces in one run.

### Inventory records

| Field | Meaning |
|---|---|
| Identity fields above | Live target and verified ASIN ownership, including targets absent from performance reports |
| `campaign` | Human-readable current campaign name; never the sole ownership check |
| `observed_on` | `YYYY-MM-DD` date of the live snapshot |
| `strategy` | Current normalized Amazon bidding strategy; use the same nonempty value on its recommendation. For example `down_only` is a normalization convention, not a promised API enum |
| `current_bid` | Current base bid in USD, not actual CPC |
| `effective_bid_multiplier` | Verified worst-case combined multiplier relevant to this test, including applicable placement/dynamic settings; unknown is not 1 |
| `gates` | Source-verified booleans listed below; missing/null is unknown, not true |
| `demand` | `{ "known": true/false, "available": true/false, "source": "...", "as_of": "YYYY-MM-DD" }`; do not assert adequate demand from recommendation presence alone |

`gates` keys: `campaign_enabled`, `ad_group_enabled`, `target_enabled`, `ad_eligible`, `in_stock`, `featured_offer`,
`budget_available`, `schedule_open`, `negatives_clear`, `routing_clear`, `ownership_clear`.

Read all pages and set `inventory_complete: true` only when product ownership and the full intended inventory are
verified. A false/currently unknown gate must not be “fixed” by marking it true. Current schedule eligibility also
does not by itself establish the historical eligible days in the delivery record.

For a proposed **Discovery target exception**, inventory additionally needs `query_mix_review`:
`{ "reviewed": true, "exact_owner_checked": true, "source": "...", "as_of": "YYYY-MM-DD",
"reason_to_test_target": "..." }`. The date must pass the recommendation-age gate. Cite the reviewed shopper-query
mix, verify the existing exact owner/routing, and explain why testing this particular broad/phrase target is better
than isolating the proven query. Without that evidence the result stays `needs_bounds`; a provisional suggested-low
amount may still be visible but is not a bounded/approved candidate. Discovery rows with delivery evidence carry
`prefer_exact_query_validation` regardless of whether an exception is proposed.

### Scheduled pauses and bid-only work (Kim, 2026-10-24)

Do not skip optimization because a pull happened at night. Read the Ads profile timezone, exact-ID SI assignment,
direct-rule precedence and the complete weekly schedule. Verify that the pause is scheduled using status history,
an observed ON/OFF transition or an explicit user confirmation tied to this product and snapshot. Clock time or a
rule's name alone is insufficient. If the change log is empty, say so; do not invent a history event.

Keep every observed `gates` value unchanged. Add `dayparting` to the inventory row, with the same `asin`,
`campaign_id`, `ad_group_id` and `profile_id` (when supplied), plus:

- `rule_id`, `timezone` (currently only `America/Los_Angeles` supported by the deterministic exception),
  `observed_at` (offset-aware timestamp; its SGT date must match `observed_on`);
- `weekly_hours`: seven arrays, Monday first, each with 24 literal booleans from the effective rule;
- `assignment_verified: true`, `resume_managed: true`, `manual_pause: false`,
  `pause_reason: "scheduled_dayparting"`;
- `assignment_source`, `schedule_source`, `pause_source`: saved evidence references, not guessed labels.

`scripts/dayparting.py` requires an enabled campaign and positive keyword, matching fresh evidence, an OFF hour
and a future ON hour. It exempts only the ad-group/schedule pause for **base-bid** work. A false `ad_eligible` gate
is exempt only when `ad_state` is `ENABLED` and the complete `ad_delivery_reasons` list consists solely of
`AD_GROUP_PAUSED` / `AD_GROUP_PAUSED_DETAIL`. Other eligibility failures, manual/unknown pauses, paused keywords
or campaigns, negatives, ownership conflicts, existing experiment controls and other guards remain effective.

The visibility review reports `scheduled_off`; it does not pretend the target is delivering. Rank routing and
replacement-dependent source cuts stay deferred. Do not count OFF hours as eligible observation time or start/reset
investment clocks. Re-read the same evidence before execution and preserve schedules/states. Audits execute any day; verify active SI modifiers and reconcile stored base bids as described in weekly-run.md. Prepare a same-run continuation when a
previous audit wrongly held these bids; subtract prior applied raises from its weekly cap and never repeat creations.

### Delivery records

| Field | Meaning |
|---|---|
| Identity fields above | Exact inventory join |
| `start_on`, `end_on` | Inclusive source-normalized dates; preserve source reporting timezone in the raw evidence |
| `complete` | True only after complete daily pulls joined to inventory; missing report rows are not automatically zeros |
| `eligible_days` | Verified eligible observation time, accounting for approved schedules and blockers |
| `impressions`, `clicks`, `orders`, `spend` | Aggregated observed delivery for that window; retain genuine zeros; spend is USD |
| `click_goal`, `goal_days` | Evidence-backed qualified-click goal and its evaluation period; no universal default is invented |
| `attribution_mature` | Whether conversion outcomes are sufficiently mature to evaluate; this does not postpone spend safeguards |

Optional diagnostic benchmarks are `ctr_floor` with `ctr_min_impressions`, and `cvr_floor` with `cvr_min_clicks`.
Floors are fractional rates, not percentages. Supply a relevant dated benchmark and sufficient sample rationale;
the engine does not invent a CTR/CVR minimum. The poor-conversion flag additionally requires
`attribution_mature: true`. Without these optional fields the module cannot diagnose low CTR/poor CVR merely from
the words “many impressions”; the operator must review those metrics separately. Actual CPC above the estimated
breakeven value and immature conversion are also surfaced as flags rather than proofs of loss.

Build these aggregates from small daily/two-day reports without a positive-spend filter, then left-join to the
full inventory. Keep daily source files for audit. The existing `recent_kw.json` positive-spend safety sweep is a
different input and cannot establish complete zero-delivery history.

### Recommendation records

Identity fields plus `fetched_on`, `strategy`, `low`, `median`, `high`, `source`. Use positive, ordered USD values
from the raw contextual response; retain the source identifier/path and tool name. A malformed, future-dated,
stale or strategy-mismatched response is not a usable suggestion. `source` must identify evidence, not an LLM's
estimate. Unsupported or unavailable recommendations remain missing.

Freshness settings are in `config.json visibility`: snapshot age at most **2 days**, delivery end age at most
**2 days**, recommendation age at most **7 days**. These are data-quality gates, not permission to execute against
stale live settings: re-read before every approved write.

### Experiment records

Identity fields plus:

- Lifecycle: `experiment_id`, `state`, `stage`, `attempt`, `start_on`, `review_on`, `end_on`, `stage_eligible_days`,
  and `stage_started_on` for an active low-stage escalation review.
- Bounds and goal: `click_goal`, `max_base_bid`, `max_effective_bid`, `max_spend`, `max_loss`.
- Consumption: `spend_to_date`, `loss_to_date`, with dated evidence. Net ad loss means ad spend less estimated
  attributable contribution, not ad spend less revenue; do not subtract speculative future organic gains.
- Approval: `approval` with `state`, `by`, `reference`, `experiment_id`, `asin`, `keyword_id`, tied to the exact
  reviewed experiment. A generic approval of the engine or an old unrelated rank test is not sufficient.

Supported `state` values are `proposed`, `approved`, `active`, `completed`, `stopped`, `expired`, `cancelled`;
supported `stage` values are `initial`, `low`, `median`. `attempt` and `click_goal` are positive integers. Dates must
satisfy `start_on <= review_on <= end_on` and the configured window, currently at most 14 days. The maximum base bid,
effective bid and spend are positive numbers; maximum loss may be zero. Track `loss_to_date` as a nonnegative
consumed loss amount, not as a negative number for an overall profit. Approved/active records require nonnegative
`spend_to_date` and `loss_to_date` plus a named, source-linked approval with `state: "approved"`. Approval alone is
not proof that the experiment launched; `active` needs live activation evidence.

Supply actual numbers per reviewed target; this guide does not invent a universal dollar allowance. Preserve the
original lifecycle and consumed allowance across weekly runs. Closed, expired or exhausted experiments do not
restart because another run is generated. Their `stop_review` takes priority over later missing-inventory or
serving-blocker diagnostics, so a data problem cannot hide an expired/exhausted allowance. Staged low-to-median
consideration requires at least seven eligible days **after the low stage actually started**: `stage_started_on`
must be on/after `start_on`, the delivery window must begin on/after `stage_started_on`, and `stage_eligible_days`
cannot exceed the observed calendar time at that stage. Pre-change traffic cannot qualify an escalation. It is
still a proposal, not an automatic auction write.

## Run and output

From the skill folder, run the normal planner and preview:

```text
python scripts/plan.py --asin <ASIN> --run <run-folder>
python scripts/preview.py --out <run-folder>/preview.html <run-folder>/plan.json
```

In the weekly run, save the team's decisions first and give the planner the day (`reviews --save`, then `plan.py ... --today
<day>`): it refuses to plan without them when the product holds a Bids item. See [weekly-run.md](weekly-run.md), steps 4 and 5.

The planner emits `visibility_review.json`, `need_visibility_data.json` and the same review inside
`plan.json.visibility_review`. Review rows retain identity, baseline/current bid, status/reason, delivery metrics,
recommendation context, experiment state and any separate proposal. `needs_bounds` means concrete limits are
missing; a provisional suggested-stage amount may be displayed, but it is not an authorized increase. Read
`need_visibility_data.json` and gather missing evidence
before treating a gap as resolved. An old snapshot can still show baseline planning with missing-context flags;
it is not proof of a completed delivery review.

Principal output statuses are `missing_data`, `blocked`, `waiting_data`, `healthy`, `review_traffic`,
`limited_demand`, `under_delivering`, `trim_no_rescue`, `needs_bounds`, `candidate`, `active_experiment`,
`review_experiment`, `rank_review` and `stop_review`. `reason_code`, `reason`, `flags` and `missing_requests` explain the next action.
`healthy` describes click pace, not proven conversion/profitability; retain its diagnostic flags. `candidate` means
a bounded preview, never “applied.” `stop_review` requests a stop/rollback decision or the already approved stop
action; the local script does not send that write itself. Do not escalate from median automatically to high.

Recommendation matching occurs early so healthy and Trim rows can show their contextual ranges too. Missing
ranges remain explicit requests; they do not alone hold a healthy non-rank target or override an intentional
economic Trim. A fresh, preflight-clear Trim can continue its usual reviewed reduction without delivery metrics,
unless an existing tracked experiment conflicts. Neither case authorizes a visibility increase.

Visibility proposals are **not** Amazon payloads. Guarded rows keep their live bid rather than silently modifying a
retained experiment or acting on an unresolved delivery check. Ordinary unrelated baseline changes retain their
usual preview/approval gate (the one exception is an enabled product's Auto lane: [rulebook.md](rulebook.md) section 7).
After a separately approved experiment, perform fresh live checks, use the normal
MAP apply/verify process, and record the exact values, original clock and consumption in the next run's input.
No ongoing monitor, job queue or autonomous executor is installed by this module.

### Applying regenerated plans safely

The planner also writes `<run>/payload_manifest.json`: the authoritative list of current payload filenames, row
counts and SHA-256 hashes, with the ASIN, `shadow` and `approval_required: true`. Previous planner-generated payloads
are preserved under `<run>/payload_archive/<SGT-timestamp>/` during regeneration. Files left elsewhere or archived from
an earlier plan are **not current apply instructions**.

Since 2026-10-19 the payloads sit in lane folders, and the manifest names them by folder:
- `<run>/payloads/auto/*.json`: the Auto-lane rows of an enabled product (empty in shadow);
- `<run>/payloads/review/*.json`: the rows a person decides;
- `<run>/payloads/held/*.json`: what the planner or a person's earlier decision holds. The manifest lists these apart
  under `held_files`; they are **never** applied;
- `<run>/payloads/approved/*.json`: built later by `dashboard.py approvals`, so not in the manifest.

Apply files from `<run>/payloads/` only by the rule of their folder, which is in
[weekly-run.md](weekly-run.md) ("Which payload folders may be applied", steps 12 and 13):
`auto/` on an enabled product, after current execution checks pass; `review/` only on Kim's whole-run yes while nobody has decided
rows of the run's item on the dashboard; `approved/` after `approvals` and current execution checks. Each folder is checked with
`dashboard.py applied ... --dry-run` before it is applied and recorded with `applied` after.

After a fresh preflight (and, outside `auto/`, exact-scope approval), apply only files named in the current manifest,
verify their hashes and match the reviewed plan/ASIN.
Never glob every JSON file, apply archived payloads, `held/`, a `rows.json` or `applied_rows.json`, or treat the manifest
itself as approval (`approval_required: true` stays on for `auto/` files too: it means that being in the manifest is not
approval). If a file/hash or planned action differs, stop and reconcile before writing. Visibility and separate
rank-experiment proposals are rejected from the ordinary payload writer; they require their own reviewed execution
preparation.

## Maintenance and sources

Keep `scripts/visibility.py`, its tests, planner/preview integration, `config.json visibility` and this contract in
sync. Never “repair” missing fields by copying another product or match type. Product files, approved rank
experiments and the Oct 19 product-target policy are not migration fixtures and must not be rewritten by this work.

Amazon references reviewed 2026-10-19:

- [Amazon's brand-foundation guide](https://advertising.amazon.com/library/guides/creating-your-brand-foundation-on-amazon): suggested bids use recent auction information; they are not YourBrand's contribution target.
- [Amazon performance estimates](https://advertising.amazon.com/help/GHFYQ2D4LQC5ABPW): estimates are not guaranteed outcomes and do not account for budget constraints.
- [Amazon bidding strategies](https://advertising.amazon.com/help/GCU2BUWJH2W3A8Z7): strategy affects how submitted bids participate in auctions; retain strategy/placement context.
- [Amazon digital-advertising basics](https://advertising.amazon.com/library/guides/basics-of-digital-advertising): impressions, clicks and conversions describe different stages, not one interchangeable success metric.

The role thresholds, eligible-day review, trial duration and safeguards here are **YourBrand's policy**, not
universal Amazon requirements. A suggested range can inform a controlled test; only measured delivery and
attributable economics can show what happened.
