# Live checks before any write

The 90-day reports miss idle objects, and Scale Insights changes things overnight. Each check below caught a real
problem on the bookmarks launch (2026-10-17). Run them after planning and again right before applying if more
than a few hours have passed.

## (a) Idle duplicates: reuse, don't create

- **Check.** Before creating an exact campaign, look for one that already exists for the search.
  - `plan.py` does this from `campaigns.json` and emits "Reuse exact campaign" rows. Without campaigns.json it
    can't, so always pull it.
  - For each reuse row: `list_resources sp_keywords` with that `campaign_id` (all states) to get the exact keyword
    ID and current bid. Plan: keyword bid → new bid; campaign budget + complete dynamicBidding.
- **Pilot:** 7 of 14 "new" campaigns already existed, with zero spend. One was Cross "christian bookmarks" at
  $0.04. Creating them would have duplicated the search.
- **Also look** for enabled exact copies of invest searches in other campaigns at high bids, for example
  "Search terms w sales - Exact - 1" with "bible bookmark" at $1.30. Pause them if they could outbid the owner.

## (b) Self-blocking negatives in exact campaigns

- **Problem.**
  - Amazon applies close variants (plurals, "book marks" vs "bookmarks", "bookmarkers") to negatives, not just
    to positive exact keywords.
  - Scale Insights' blacklist pushes negatives into every ad group it's assigned to.
  - So an exact SKC can carry a negative that blocks its own search and go dark with no error.
- **Pilot.** Cross "bible bookmark" at $1.30 had zero impressions from 2026-07-10, because of a negative exact
  "bible bookmarks" in its own ad group.
- **For each entry in `checks.json`, and each reuse row:**
  1. `list_resources sp_negative_keywords` with `ad_group_id` and **no** `keyword_text_filter`, every page. A stem
     filter misses one-word phrase negatives: on 2026-10-17 four notebook exact campaigns held phrase negatives "for",
     "work" or "aesthetic" that blocked their own searches, and a "notebook" stem didn't return them.
  2. Save the output and run `python scripts/close_variants.py "<SKC keyword>" negatives.json`. It prints the
     negatives to archive: exact close variants of the keyword, and phrase negatives whose words appear in it in order.
  3. Archive them (map-playbook.md, "Archive a negative") as part of the approved launch. Explain: this negative
     blocks the campaign's own search.
- **Prevention.** SKC ad groups sit on strategy 302497 with the blacklist unassigned, so SI no longer adds new
  ones. Still check weekly: someone may reassign.

## (c) Out-of-plan spend

- **Problem.** Keywords with no 90-day spend aren't in the plan, but they wake up when dayparting or budgets open.
- **Pilot.** 13 Scenery keywords at $1.26–1.30 spent $14.89 in two days with 0 orders.
- `plan.py` folds `recent_kw.json` into step 5, but only lowers bids.
- Anything else odd (targets, SB) goes in the message to the user.

## (d) Scale Insights state

- **No competing bid rules.** On the Assigned rules page, no bid rules except the approved reduce-only 202 Brake
  on strategies 101, 111 and 121. Exact owners on 103 must not carry that brake or another bid rule.
- **SKC strategy and blacklist.**
  - SKCs are on 302497 with BlacklistFilter empty.
  - Newly synced campaigns aren't left unassigned. Unassigned means no dayparting. They also must not be on a
    strategy with bid rules.
- **Whitelist.** It holds every invest and prove-first search.
- **Dayparting.** Read the DayPartingFilter.
  - "Minimal - Only 5-6am" next to Optimum Hours means the product runs one hour a day wherever Minimal wins.
  - Standard authorized onboarding replaces legacy direct schedules with 203 / 21246 and verifies effective
    coverage (Kim, 2026-10-24; onboarding.md section 7). Preserve shared exclusions and explicitly approved
    schedule exceptions. Other dayparting changes still require the user.
  - A scheduled OFF snapshot does not suspend economic bid optimization. Classify the pause using the exact
    effective rule, marketplace-local clock and evidence of scheduled control; use the `dayparting` inventory
    contract in [visibility.md](visibility.md). Keep actual states intact. Manual/unknown pauses and other blockers
    remain held; delivery-dependent routing and clocks still need actual serving.

## (e) Placement settings

`update sp_campaigns` resets any placement you omit. Send every existing placement back:

- `plan.py` copies `other_placements` from campaigns.json into the payload;
- without campaigns.json, read the campaign first.

## (f) Delivery is not the same as a low bid (2026-10-19 SGT)

Before any visibility-test or coverage-recovery proposal in [visibility.md](visibility.md):

1. Match the candidate to the live ASIN, campaign, ad group, target ID, text and match type. Read its current bid,
   state, ad product, placements and bidding strategy. Do not transfer another match type's suggestion to it.
2. Check inventory/buyability, advertised-product eligibility, campaign/ad-group/target state, budget exhaustion,
   approved schedule and direct schedule overrides. If a connector cannot establish a check, record unknown.
   Do not relabel a scheduled pause or a missing report as bid starvation.
3. Inspect all relevant negatives and ownership routing. Existing owner/routing holds remain in force until the
   approved destination is verified delivering. A visibility recommendation is not approval to archive negatives,
   reopen a paused duplicate, unpause a scheduled group or modify SI rules.
4. Confirm the recommendation's source date, real context and complete low/median/high range. A suggested low is
   auction guidance, not a minimum delivery guarantee. Review the effective bid after every applicable placement
   and dynamic setting; the baseline economic CPC and paid CPC are different quantities.
5. Confirm a complete inventory-plus-daily-report join and at least seven verified eligible days before diagnosing
   inadequate test delivery. Demand and the evidence goal determine a reasonable pace; no universal minimum number
   of impressions applies. Separate low demand, low CTR, weak conversion and missing data.
6. For any proposed experiment, show its exact scope, maximum bid, spend and net-loss allowance, duration, review
   point and rollback. The 14-day default proposal is not approval. Preserve existing approved rank experiments
   and their original clocks. Re-read immediately before an approved write; if the action materially changes,
   return to the person rather than expanding the approved scope.

Record actual applied values and read-back evidence separately from the diagnosis/proposal. The visibility report
does not launch, schedule or execute changes by itself.
