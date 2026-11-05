# Needs human queue

Added 2026-10-18 SGT at Kim's request. The dashboard's **Needs human** tab (`#/needs-human`)
collects listing-optimisation and price decisions across products. It is a read-only team queue,
not a way to edit Amazon listings or prices. Product pages also show their active reviews.

**People see decisions only (Kim, 2026-10-22, decision 97).** Kim: "will it be ok to not report these AI
research notes to the humans. just show them the proposed dashboard changes", and "finish the AI research for the
ASINs autonomously ... only shows actual decisions humans actually need to make, that the AI can't decide or is a
borderline decision about." So:
- The AI finishes the research below on its own in every run. Nobody is asked to do it or read it.
- Only items in phase `human_ready` are published (`human_review.attach` through `for_people`): a listing, image,
  offer or price call the AI can't make, or a borderline one, plus the run's Bids item. Each is published without the
  research write-up. Its action is the AI's recommendation, with its confidence. Rationale, counterevidence, query
  tables, competitor offers and open checks stay in the product file for the AI. The For Growth item (`kind: "growth"`,
  the end of this page) is published too, whole: it is Growth's work order, not a decision, and has no write-up to cut.
- Items still in research, and items the AI only monitors, are never published. The next run finishes them.

**Who decides each kind** (`approval_required`, set by `human_review.validate`; Kim, 2026-10-22, decision 95):
- `listing`: **Lee**, the team leader. The harder product calls are hers: when to revamp a product's images, when
  to cut (stop or discontinue) a product, and when to improve its listing or offer.
- `price`: **Kim**.
- `bid` (the weekly Bids item): each row carries its own level, the book owner's or Kim's (rulebook 7.10). A row
  Lee declined asks for her again.
- `growth` (the For Growth item): nobody. It has no `approval_required`; Growth runs the pass with the block (the end of
  this page).

## Every routine sweep

1. `plan.py` emits `human_review` alongside its bid plan. It uses the existing rulebook:
   trusted SQP/ad data, same-query market data, index below 0.8 and at least 15 clicks flag a
   AI research candidate, not an immediate human task. Thin data, irrelevant queries and product-average market
   fallbacks do not generate this alert. CVRs/index are labelled as smoothed decision values.
   One weak query is a query-level signal, **not proof that the entire ASIN is below market**.
2. Complete the [AI market research pass](market-research.md) before escalating, yourself, in this run. Rank sufficiently
   sampled opportunities by **IDX × 30-day-normalized SQP search volume**, within semantic relevance
   tiers; exact match type does not prove exact product fit. Research both the best opportunities and
   weak direct-fit queries, so low IDX does not hide a genuine listing issue. Read live Amazon.com
   search results and comparable offers. Save the dated observations and AI judgment in
   `<run>/market_review.json`; `market_review.py` computes scores and checks evidence completeness.
   The LLM reviews the signal and listing/offer evidence. Check relevance, image/copy mismatch,
   reviews, price and offer before attributing the problem to the listing. It can add a separate
   evidence-backed hypothesis even when the deterministic trigger did not fire; disclose
   missing data rather than inventing a conversion diagnosis.
3. Review pricing on every sweep: higher, lower, or unchanged. Weak conversion prompts a price
   positioning review, never an automatic cut. Strong sampled conversion with negative product
   profit prompts a neutral offer/price investigation, not an automatic increase or amount.
4. Put LLM-authored items in `<run>/human_review.json` (a list). Rerun `plan.py` to include them.
   All manual and generated items pass the same market-research gate. A matching stable ID replaces the generated proposal; use `listing-conversion-gap` or
   `price-positioning` for those recurring issues. Distinct issues get distinct IDs.
5. Include the queue proposals in the person's preview and obtain explicit publication approval.
   `dashboard.py publish --dry-run --out <file>` previews the merged queue. A successful approved
   publish saves it in the product's `human_review` array, with the rest of the product state.
   `lineup` and `refresh` carry the saved queue too. Old products with no queue remain valid.

## Item contract

Required: `id` (stable lowercase slug), `kind` (`listing` or `price`; the weekly Bids item is `bid` and the Growth team's listing pass is `growth`, see the end of this page), `title`, `reason`, `action`,
`source`, `window`. Use `evidence` for a list of dated factual notes or structured query rows
(`query`, `basis`, `clicks`, `purchases`, `our_cvr`, `market_cvr`, `index`, `note`). Ratios are
fractions, not whole percentages. The window and source must distinguish SQP from ad fallback.

Optional workflow fields: `owner`, `priority` (`high`, `normal`, `low`), `status` (`open`,
`in_progress`, `waiting_approval`, `resolved`, `dismissed`), `first_seen`, `last_seen`.
The publisher preserves status, owner and history across sweeps; a missing signal never silently
closes an issue. A resolved signal detected in a later sweep reopens with history. Dismissed
items remain dismissed until a human explicitly reopens them.

`ai_review.phase` is separate from human status: `research`, `human_ready`, or `monitor`.
Missing/legacy research defaults to `research`, not human-ready. The tab opens on human-ready
items and links to AI research and monitor lanes. Existing flags, owners and history are retained.
This is not a background AI service: the sweeper's LLM must perform the research pass during a run.
A fresh sweep invalidates old research unless matching, newly dated evidence is supplied.

### Price suggestions

Set `price.direction` to `increase`, `decrease` or `review`. An unpriced investigation can keep
`proposed: null`; the UI says that no amount has been proposed. Never invent a universal step size.
For a concrete increment/adjustment, `price` must contain:

- `current`, `proposed`: verified effective current price and proposed test price in USD.
- `profit_per_unit_current`, `profit_per_unit_proposed`: contribution before advertising,
  recomputed from current costs, applicable referral/FBA fees and discounts, not price delta alone.
- `economics_as_of`, `economics_source`: dated fee/cost/offer evidence.
- `comparison_source`: dated like-for-like pack/size competitor evidence, with references.
- `review_on` (SGT date) and `rollback`: the test review and measurable reversal condition.

The UI shows current → proposed price, contribution change and margin before ads. **Kim approves
all price changes**, separately from routine bidding. A queue status is not approval, and resolving
an item does not change a price. Follow rulebook §6: one change at a time, review the invest index
within three weeks, and recompute product economics the day an approved price goes live.

## Assign / resolve without erasing history

Use the local product-state command; preview first:

```text
python scripts/dashboard.py review --asin <ASIN> --id listing-conversion-gap --status in_progress --owner Lee --note "Gallery audit assigned" --dry-run
```

Run without `--dry-run` to save locally, then preview and approve a normal dashboard publish/refresh.
Use `--status resolved` or `dismissed` with a specific outcome in `--note`. No live write happens
in `review`. There are deliberately no unauthenticated status-edit or price-change buttons on the
public dashboard. Commit product state and run records only when asked.

## Why a bid row waits for a person: the data-stage reasons (2026-10-22)

The queue above is for listing and price decisions. The Bids item has its own rows, each with a lane and a reason (rulebook
7.2), and from 2026-10-22 a promotion can wait for a person for the reasons below (rulebook section 10, `scripts/lanes.py`
`_stage_hold`). They are checked in this order, after the lock, stale-data and cut rules, and only
for consumer promotions and for a live rank campaign's policy-only top-of-search row on an Invest or Prove first search. The
second reason is the exception: it belongs to a raise (a `Bid change` on a fallback search's live keyword), which `classify`
checks after the promotions. A cut is never held by any of them, and nor is a business row (rulebook section 9). In shadow
every row waits for a person anyway; these say which rows the planner would not have applied by itself.

**Since autonomous runs (2026-10-22, decision 98)** the first four still park the row "For human"; the last two (a volatile
week, one SQP week) hold it instead (Monitor: not applied, not escalated), because the next week's data settles them. The
full human list is in rulebook 7.9 (since decision 107, 2026-10-23, no bid or rank call is on it: close calls, big cuts, a non-standard budget, the search-term fallback and the run's raise count are the AI's; their old reasons below are history); each parked row gets one line in the run's Slack message (`scripts/notify.py`), tagging
who decides.

| The why column reads (exact text) | Why | What the person decides |
|---|---|---|
| `one-word search: a head term, generic and hard to rank on, so a person decides (rulebook section 10)` | The `relevance_flag` is "one token" (10.3, item 4). Every stage. Kim, 2026-10-21: "pen" is generic and broad | Whether the head term is worth a rank campaign: Kim, 2026-10-21, called "pen" generic, broad and very hard to rank on. A yes is a lock for 4 weeks (7.8) |
| `not in the product's niche list, its launch list or its roots, so a person decides whether it is the product's search (rulebook section 10)` | The `relevance_flag` is "unlisted" (10.3, item 4). Only on a product with a launch list, a `niche_keywords.json` in the run or roots. Every stage | Whether the search is really the product's ("school supplies" was one on the gel pens' 2026-10-22 probe) |
| `volatile SQP week: the SQP since <baseline date> (through <this run's date>) added <n> of our clicks, more than the <n> of all earlier weeks; promotions wait for a steadier week (a person may lift the hold with --allow-volatile)` (held, Monitor, since 2026-10-22) | Stage early only: this run's SQP added more of our clicks than all the weeks before it (10.4). The span is the baseline's `sqp_history` entry to this run's SQP date, normally one week. A ratio other than 1 reads "more than <ratio> x the <n>" | Whether the week is real. `plan.py --allow-volatile` lifts the hold once someone says so |
| `early SQP: seen in one SQP week only (<days> observed days, under 14), so it waits for its second week` (held, Monitor, since 2026-10-22; until then "so a person decides until its second week") | Stage early only: the search's SQP row has fewer than `stage.auto_min_observed_days` (14) observed days (10.3, item 1) | Nothing since 2026-10-22: the next run judges it on its second SQP week |

**The evidence text.** A Rank row's evidence (the Why of a promotion in the preview) ends with where its index and its volume
came from, and its flag: `basis: <index basis>; volume: <volume basis>` and, when flagged, `; flag: one token` or
`; flag: unlisted`. The index basis is SQP, SQP (thin), Search terms, Search terms (thin), "Search terms vs product market" (the
fallback) or No clicks yet. The volume basis is SQP, launch list, SoldScope or none. A volume from the launch list or SoldScope
also reads "<n> searches in <days> days (<basis>, scaled from a monthly figure)", where an SQP volume reads "searches in 12
weeks".

## Kind growth: the For Growth item (added 2026-10-22)

The Growth team's listing pass is a `human_review` item of `kind: "growth"`, `id: "for-growth"`, one per ASIN. It
follows the item contract above, but it is not a Needs-human item and not an approval. What it is, its rows and its
lifecycle are in [for-growth.md](for-growth.md); what differs from the items above:
- **Published whole.** `human_review.for_people` (decision 97) passes it through as it is, like the Bids item: it is
  `human_ready` by construction and has no research write-up, so its `growth` block, its own `action`, its status fields
  and its history all reach the page. The For Growth tab, the product page's section and the status route read it there.
- **Out of the queue.** `human_review.attach` leaves it out of the Needs-human counts, the dashboard's queue guard leaves
  it out of "N decisions need you", and the preview (decisions only, decision 97) gives it no tile, only one line in a
  For Growth part of its own after the decisions: "For Growth: <pass> block produced (see the For Growth tab)" when
  this run raised it (`summary[0].growth_trigger`), else, for an item it only carries, "For Growth: open (<status>)
  since <opened_on> (see the For Growth tab)". It shows on the For Growth tab and in a For
  Growth section of the product page, never as a second card: wherever `humanItem` draws review items it is a one-line
  pointer to that section (since 2026-10-22, 21:27 SGT the folded Context & audit draws none).
- **No approval level.** `validate` removes `approval_required` from it: nobody signs it, Growth runs the pass with the
  block.
- **Not "For human", and never applied by a run** (autonomous runs, decision 98). It is planned and written to
  `<run>/growth.json` on every run, enabled product or not, but it is not a parked row: the run's Slack message
  (`notify.py`) names only parked bid rows and listing or price items, and the run's apply covers the plan's change
  rows, never a review item. Nothing in For Growth writes to Amazon; Growth pushes the copy.
- **Out of the market-research gate.** Its rows are deterministic, so `ai_review.phase` is `human_ready` by construction,
  `plan_growth` runs after `market_review.assess`, and it needs nothing in `<run>/human_review.json`.
- **Its own statuses.** `open`, `in_progress` ("Picked up"), `copy_pushed` ("Copy pushed"), `resolved` (the AI, on a
  listing change) and `dismissed` (a person, with `dashboard.py review`). `copy_pushed` is valid on a growth item only;
  `validate` refuses it on any other kind.
- **One item, updated in place.** The merge (`human_review.merge`, `_merge_growth`) keeps the stored item whole when the
  incoming block is not newer (`growth.produced`), so a plan published again or a run with no trigger never undoes a
  pickup. A newer block over an item that is not closed (a rotate-out flag) replaces the block and keeps the status, who
  set it, the owner, `first_seen` and the history. Over a resolved or dismissed item it is taken only when it was built
  as a new open item (a new pass), and the history is kept.
- **On an AI-managed product** (`registry.bid_owner` AI) it supersedes `listing-conversion-gap`: an active one is
  resolved with the note "Superseded by the For Growth item (design 2026-10-20)", and one proposed again is not reopened.
