# Confirmed wrong-size keyword pauses

Kim, October24,2026SGT: verify product sizes against the live listing, then automatically apply confirmed
wrong-size positive-keyword pauses in an authorized Auto run. A fingerprint alone still holds the pause.

## Pull and verify

When `need_listing_size_verification.json` reports `needs_live_read: true`, finish this evidence step during
the audit without asking for a new size approval. Pull one fresh listing read, save the review, then re-plan
the unapplied run (or a new continuation if the original already went out). Do not publish a final hold merely
because the first plan lacked a listing read. If that read remains ambiguous, conflicting or unavailable, keep
the affected pauses held and record the concrete reason; do not loop or weaken another guard.

For each product with a wrong-size pause, read MarketplaceAdPros `get_selling_partner_listings` using its exact
SKU and the US Selling Partner account, with `include_data: ["attributes"]`. Save the unmodified response in
that product's run folder, for example `listing_raw.json`. Read the actual title and bullets. Confirm all product
dimensions, including folded/unfolded or other genuine alternatives. Package/catalog dimensions, envelope/frame
sizes and competitor/reference sizes do not establish the product's dimensions. Resolve contradictory or
ambiguous copy before calling it confirmed. Never change the listing to make a pause eligible.

Save `listing_size_verification.json`, based on that read (the example is the napkins' actual size statement):

```json
{
  "asin": "B0SAMP0020",
  "sku": "YourBrand_712",
  "marketplace": "US",
  "source": "MAP get_selling_partner_listings",
  "raw_listing_file": "listing_raw.json",
  "observed_at": "2026-10-24T22:45:00+08:00",
  "complete": true,
  "ambiguous": false,
  "claims": [
    {
      "field": "bullets",
      "index": 2,
      "quote": "Folded to 5x5 inches, opening to 10x10"
    }
  ]
}
```

Use the real read time and exact verbatim quotes; bullet indexes start at0. `field` can also be `title` (no
index). Each quote must state dimensions with an explicit inch unit in that statement. The example quote's first
inch unit also covers the unfolded size. The review must cover all size pairs in the title and bullets, and its
sizes must include the product file/fingerprint's own sizes; additional live sizes must be explicitly allowed
in its size-specific protections (for example the napkins' unfolded10x10). A live/config conflict is a finding to reconcile,
not permission to edit the fingerprint silently. Explicit size-specific protections stay in force.

`scripts/listing_size.py` checks the successful raw response, exact ASIN/SKU, US marketplace, live BUYABLE status, verbatim claims,
units, alternate dimensions and configured sizes. The read must be from the run's SGT day, within24hours and not
in the future. Missing, stale, malformed, incomplete or conflicting evidence keeps the size hold on those rows;
it does not stop unrelated eligible rows. Unsupported metric/three-dimensional or accessory/packaging claims
also stay held. An arbitrary `verified: true` flag is insufficient.

## Planning and execution

The planner stamps `listing_size_verified_pause` only on an identified positive-keyword relevance pause
(`Pause keyword` or `SB pause keyword`, role `Negate`) whose requested dimensions are all outside the allowed
sizes. A mixed query containing an allowed size remains held. This removes only its size-specific hold; normal
lane classification still applies. Replacement/routing pauses, increases, promotions, new campaigns, budgets,
negatives, blacklist/whitelist edits and shared-campaign actions gain no exception. Wrong-size terms remain
excluded from rank investment, harvest seeds and blacklist rescue. Attributed orders do not make a confirmed
wrong-size product match; a person's existing decision or size-specific protection can still hold/prevent a pause.

For Auto-on AI-owned exclusive campaigns, eligible confirmed pauses go through the existing Auto payloads and
MAP apply sequence. No further per-row size approval is needed. Auto-off/shadow and readiness runs remain
non-executing. Ownership, human locks, fresh SQP/price/inventory, buyability, protected experiments, routing,
current exact-ID checks, readback and Day1 guards are retained. Do not unpause parents or change schedules.

Immediately before execution, re-read the listing and verify the saved evidence still describes it. Run
`dashboard.py applied --folder auto --dry-run`: for marked pauses it revalidates the run's raw snapshot/review,
age and product identity against the planned proof. Changed evidence requires a new plan before execution;
never edit an applied run or strip the evidence marker. This local check does not itself call Amazon. Apply only
the current payload, read every paused keyword back by exact ID, then record, publish and send the usual run recap.

Read this reference when a run proposes wrong-size keyword pauses. Other relevance negatives still use the
negative audit's approval table. This policy changes no bid/price thresholds and does not disable any guard.
