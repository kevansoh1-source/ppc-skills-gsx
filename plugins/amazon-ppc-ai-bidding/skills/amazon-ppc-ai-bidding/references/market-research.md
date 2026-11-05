# AI market research before human escalation

Requested by Kim, 2026-10-18 SGT. Local implementation; publication needs preview approval.
This changes the review workflow, not bidding thresholds, placement experiments or live prices.

## Separate intent from conversion

Classify each sufficiently sampled query against verified product contents, format, size, material,
audience and use case. Give a reason and source, not just a label. Never infer relevance from high
CVR, a keyword substring, or the advertising match type. Keep unknown claims unknown.

- **direct**: explicitly describes what the ASIN offers, e.g. animal bookmarks for animal bookmarks.
- **adjacent**: plausible substitution/use, but some buyer expectations may differ.
- **broad**: many unrelated product types satisfy the intent, e.g. gifts for children in school.
- **mismatch**: an explicit requirement the ASIN does not meet. Not permission to negate it.
- **unknown**: listing/intent evidence missing; AI must investigate before escalation.

A broad query can be worth testing despite low CVR; it is not evidence that the whole ASIN is
defective. Conversely, do not excuse weak direct-fit searches as merely broad. Report both
supporting and contrary evidence; never average query CVRs into an unsupported ASIN-market IDX.
Manual, independently verified listing defects can still be recorded, but are not confirmed by a
conversion-only signal. No automatic listing, price, bid, negative or dashboard writes.

## Opportunity shortlist

Use the existing sufficient-data rules, same-query market benchmark and smoothed decision IDX
(1.0 = market parity, not a 100-based score). Skip thin samples. For each eligible query:

`30-day searches = SQP QueryVolume × 30 / QueryObservedDayCount`

`opportunity = IDX × 30-day searches`

The planner already stores these as `index`, `sqp_volume`, and `observed_days`. Do not substitute
ad impressions, clicks or an unspecified search-volume source. Missing volume/days means unranked,
not zero opportunity. Keep actual window, raw volume, observed days, samples and source visible.
Short-window seasonality and ad/SQP traffic-mix differences remain limitations.

Sort direct and adjacent queries separately by descending score; broad/mismatch/unknown rows
remain visible but unranked. This score prioritizes research; it is not expected sales, profit,
incremental orders, statistical significance or a bid multiplier. Look at the top three available
direct and top three adjacent queries, plus weak direct-fit queries even if their score is low.
This research shortlist is not a cap on keyword exploration.

## Inspect Amazon.com, not just a search-engine snippet

Use the browser or an available approved connector. Read actual Amazon results and competitor
detail pages. If access is blocked, record the blocker and leave AI research pending; do not call
search snippets live price verification or bypass a CAPTCHA. No paid niche/radar creation.

Record the query/search URL, observation date (SGT), location/delivery context, sponsored versus
organic result mix, dominant product formats, competing pack sizes and expectations. Save evidence
under this ASIN's run folder. Select competitors from these results rather than cherry-picking
cheap or expensive examples. Record exclusions and why they are not comparable.

Assess our entire offer: pack quantity, usable unit count, size/material/finish, design variety,
included accessories, reviews/rating, fulfilment/delivery, stock, main image, gallery clarity and
claims. Compare price per pack AND per equivalent unit. Do not compare a sticker sheet to one
individual sticker, a printable to a physical product, or blank cards to occasion-specific cards
without explicitly explaining the difference. Coupons are conditional, not universal prices;
record clipped/Prime/subscription restrictions, shipping and effective-price assumptions.

At least two distinct in-stock comparable competitor ASINs with current dated evidence are needed
for a relative-price judgment. This is a minimum evidence check, not a representative-market claim.
The code computes unit prices and a descriptive median; the LLM must still explain whether quality,
reviews, delivery and bundle differences justify a premium/discount. Below-median price alone is
not proof of underpricing; above-median price alone is not proof of overpricing.

## Saved input contract

`market_review.json` is an object with:

- `asin`, `as_of`: exact product and sweep date. Stale or cross-ASIN files are rejected.
- `queries`: `{query, relevance, reason, source}` for sampled queries.
- `searches`: `{query, url, observed_on, result_mix, findings}` from live Amazon.com results.
- `own_offer`, `competitors[]`: each has `asin`, `title`, `url`, `observed_on`, `effective_price`,
  `pack_count`, `unit`, `availability` (`in_stock` when verified), `discount_terms`, `rating_context`,
  `comparison`. Competitors additionally have `query` (a selected opportunity) and boolean
  `comparable`. Use HTTPS Amazon links; record real observations, not synthetic placeholders.
- `assessment`: `conversion_verdict` (`listing_candidate`, `query_mismatch`, `mixed`, `insufficient`),
  `price_verdict` (`underpriced`, `overpriced`, `fair`, `uncertain`), `rationale`, `counterevidence`,
  `recommendation`, `confidence` (`low`, `medium`, `high`). These are AI judgments, not measured facts.

Missing evidence / uncertain judgment / low confidence stays in `research`. A supported query-fit
explanation or fair-price/no-change assessment goes to `monitor` without closing/deleting the issue.
A supported direct-fit gap or offer/price decision goes to `human_ready`, retaining the original
signal and human assignment/history. Listing readiness requires sufficiently sampled direct-fit
weakness; adjacent/broad weakness alone cannot satisfy it. Numeric price tests still require dated
economics, full contribution/margin calculations, review date, rollback and Kim approval.

`plan.py` automatically loads this file after manual human-review overrides. To reassess saved
reviews without regenerating approved advertising plans:

```text
python scripts/market_review.py --plan <saved-plan.json> --product data/asins/<ASIN>.json --research <run>/market_review.json --date YYYY-MM-DD --out <run>/reviewed-human-items.json
```

Omit `--research` to build a truthful evidence-gap checklist, never to imply research was completed.
Preview changes before publication. Never silently replace saved bid/TOS proposals during this pass.
