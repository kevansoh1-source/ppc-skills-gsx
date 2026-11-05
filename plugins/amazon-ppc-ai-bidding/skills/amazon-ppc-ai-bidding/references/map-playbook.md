# Applying through MarketplaceAdPros

IDs are in `config.json`:
- `amazon_ads.integration_id` + `account_id` for every ads call;
- `selling_partner.account_id` for listings.

**Every write rules.**
- Put a `note` on every write that says what and why. It is saved to the change set.
- Record the returned change set IDs in the run log.
- Sponsored Brands campaign updates: at most 10 campaigns per request. On 2026-10-24, an 11-campaign budget request returned `INVALID_ARGUMENT`, `rangeError.upperLimit: 10`, with no SB updates; the same approved cuts succeeded in batches of one and ten. Verify per-type results in a mixed request because SP updates may succeed while the SB batch is rejected.

**MarketplaceAdPros is the only write path.** Never use Scale Insights change sets on an AI-owned product: its rules run
every evening, and its own copy of a bid can differ from Amazon's. Write during the audit on any day, and reconcile active SI dayparting modifiers and base-bid readbacks (weekly-run.md, "When you may write: during the audit").

## Which payloads you apply

`plan.py` splits the payloads into folders under `<run>/payloads/`. The file names in "Order" below are the same in each
folder. The rule for each folder is in [weekly-run.md](weekly-run.md) ("Which payload folders may be applied").

| Folder | Holds | Apply it |
|---|---|---|
| `auto/` | Auto-lane rows (an enabled product only; empty in shadow) | After current execution checks pass; no approval needed |
| `review/` | Rows a person decides | Only on Kim's whole-run yes, while nobody has decided a row of the run's item |
| `held/` | Rows the planner, a person's earlier decision or a rank experiment holds | **Never** |
| `approved/` | Rows the team approved on the dashboard, written by `dashboard.py approvals` | After `approvals`, after current execution checks pass |

- **`rows.json`** sits in every payload folder: `{file name: [row_id behind each payload row]}`. It is a record, not a
  payload: never send it to MAP. `dashboard.py applied` reads it to know which rows went out.
- **`payloads/applied_rows.json`** records what went out, `{row_id: {date, folder}}`. Only `dashboard.py applied` writes it.
  It is not a payload either, and neither is `payloads/approved_decisions.json`.
- **Before a folder:** `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder auto|review|approved --dry-run`.
  **After** the apply went through and every row was read back: the same command without `--dry-run`.
- **If a step fails, stop and say so.** A folder that was only partly applied is not recorded with `applied`, which records
  every row of `rows.json` (weekly-run.md, "Read back every row").

## Order

Apply the files of one folder, made by `plan.py`, in this order.

1. **New exact campaigns** (`1_new_campaigns.json`), via `create_resources`. Campaign IDs come back in input
   order.
2. **Their ad groups.** `create_resources` `sp_ad_groups`: `{campaignId, name: "Performance Exact",
   defaultBid: <bid>, state: ENABLED}`, bid taken from `1b_new_skc_specs.json`.
3. **Product ads and exact keywords**, in one `create_resources` call:
   - `sp_product_ads {campaignId, adGroupId, sku, state: ENABLED}`
   - `sp_keywords {campaignId, adGroupId, keywordText, matchType: EXACT, bid, state: ENABLED}`
4. **New B2B exact keywords** (`1c_new_keywords.json`; rulebook 9.3), after the new campaigns' keywords: one
   `create_resources` call of `sp_keywords {campaignId, adGroupId, keywordText, matchType: EXACT, bid, state: ENABLED}`,
   as written. Each adds a business invest search to the team's "B2B - Search Terms with Sales - Exact" campaign. First
   check that ad group's negatives for the search (live-checks.md): the team's Scale Insights rules negate searches with
   orders, and a negative exact there blocks the new keyword. Its campaign's budget and top of search go out in step 9.
5. **Reuse rows** (`2_reuse_specs.json`), via `update_resources`:
   - keyword bid;
   - campaign budget + complete dynamicBidding;
   - archive any self-blocking negatives found by live check (b).
6. **Business invest specs** (`2b_business_invest_specs.json`; rulebook 9.2, 9.5): **a record to read, not to apply.**
   One spec per `Business invest` row: the keyword, its ad group, its invest bid and its campaign's campaign-wide budget
   and top of search. Its writes are elsewhere: the keyword bid in `4_bids_NN.json` (step 8) and the campaign update in
   `5_campaign_updates.json` (step 9). Read it to check each owner's ad group for self-blocking negatives before the bids
   go out (live check (b); the ad groups are on `checks.json`).
7. **Pauses** (`3_pauses.json`), the business copies ("the business owner holds this search") included.
8. **Bids** (`4_bids_NN.json`): 120 per call, the business invest keyword bids included. Several calls can go in
   parallel; check `failed: 0` on each.
9. **Campaign updates** (`5_campaign_updates.json`): budgets, top of search, harvest default bid, budget steps, and the
   business invests' campaign updates. Since decision 155 (2026-10-27) also the placement policy rows (a non-rank
   campaign's top of search to 0%: the budget unchanged and every live placement sent, enabled or paused campaigns) and the
   ad-group default bids (`sp_ad_groups {adGroupId, defaultBid}`, cut only). Read the default bids back with
   `list_resources sp_ad_groups` by `campaign_id`.
   - **One update per B2B campaign,** however many `Business invest` and business `New exact keyword` rows it holds: the
     budget and the complete placement list at the campaign-wide values the planner stamped on each of its rows (the
     highest policy among them, +50% beats +30%, and the highest budget, never under live). Any subset of the campaign's
     approved rows writes the same update, so never merge or edit it by hand. A campaign not read live gets no budget,
     and a held placement no `dynamicBidding`.
   - **After every `sp_campaigns` update to a B2B campaign, read `siteRestrictions` back and check it is unchanged**
     (still `AMAZON_BUSINESS`). If it is gone, stop: a person restores it in the Ads console.
10. **Down-only bidding** (`5b_bidding_strategy.json`; decision 140, placements.md "Down-only bidding"): one
    `update_resources` `sp_campaigns` item per campaign, `{type, campaignId, optimizations: {bidSettings: {bidStrategy:
    "SALES_DOWN_ONLY", bidAdjustments: <as live>}}}`, written as planned. Before the write, read the campaign live: if its
    placement or audience adjustments are no longer what the row carries, stop for that campaign and re-plan. After it,
    read `bidStrategy` back (`SALES_DOWN_ONLY`) and every placement and audience percentage (unchanged).
11. **Negatives** (`6_negatives_NN.json`), the business funnel negatives in B2B ad groups included, plus the approved
    negative-audit table.
12. **Sponsored Brands video** (`7_sb_new_campaigns.json`): one spec per new campaign. For each, in this order, every
   step using the ids the previous one returned:
   - `sb_campaigns`: the spec's `campaign`, with `startDate` = today. Created with `bidding.bidOptimization: false`, so
     Amazon doesn't move the AI's bids. `goal`, `costType` and `smartDefault` can't be changed after create.
   - `sb_ad_groups`: `{campaignId, name, defaultBid, state}`.
   - `sb_ads`: `{adType: "video", adGroupId, name, state, creative: {videoAssetIds: [<asset>], asins: [ASIN]}}`. No
     landing page for video. `SUBMITTED_FOR_MODERATION` is normal; check `creativeStatus` later.
   - `sb_keywords`: the spec's `keywords`, at most 10 per call.
   - **Portfolio:** MAP can't set an SB campaign's portfolio. Set "3. Video Ads - Normal Bids" in the Amazon Ads
     console, one campaign at a time (no bulk move), and confirm by reading `sb_campaigns` back after 2–3 minutes.
   - Add each new campaign id to the product file's `sb_video.campaigns`.
13. **Sponsored Brands keyword updates** (`8_sb_keyword_updates.json`): bids and pauses. Write `8c_sb_bid_optimisation.json`
    (13c) first when the folder holds it. `sb_keywords` updates need
    `keywordId` and `adGroupId`. **A keyword can be in the file twice**: an older copy of a search the AI's new video takes
    over gets a low holding bid and a pause in the same run (decision 135). MAP refuses a call that names the same keyword
    twice (2026-10-26, gold notebooks B0SAMP0013: 3 pauses refused alongside their bid rows), so send the file's bid items
    first and its `state: PAUSED` items in a call of their own after them; the keyword ends paused at the low bid.
13b. **Sponsored Brands target bids** (`8b_sb_target_updates.json`; decision 155): `update_resources` `sb_targets`
    `{targetId, adGroupId, campaignId, bid}`, cuts only. Read back with `list_resources sb_targets` by `campaign_id`.
13c. **Sponsored Brands bid optimisation off** (`8c_sb_bid_optimisation.json`; decision 155): `update_resources`
    `sb_campaigns` `{campaignId, bidding: {bidOptimization: false, bidAdjustmentsByPlacement: [...]}}`: the campaign's
    saved placement modifiers with every positive one at 0 (with optimisation off Amazon applies them). Write it **before**
    13, 13b and 13d, so the keyword, target and theme bids that follow are the ones Amazon pays. Read `bidding` back.
13d. **Sponsored Brands theme bids** (`8d_sb_theme_updates.json`; decision 156, 2026-10-27): `update_resources`
    `sb_themes` `{themeId, adGroupId, campaignId, bid}`, cuts only ("keywords related to your brand" and "... to your
    landing pages"). Read back with `list_resources sb_themes` by `campaign_id`; the read-back compares them by `themeId`.
14. **Product targets** (`9_target_pauses.json`, then `9_target_bids_NN.json`; rulebook 2b): `update_resources` with
    `sp_targets` items, `{targetId, bid}` or `{targetId, state: "PAUSED"}`, 120 per call. Read a sample back with
    `list_resources sp_targets` and a `target_id` filter. Auto targets (close match, loose match, substitutes, complements)
    are `sp_targets` too.
15. **Sponsored Display targets** (`9b_sd_target_updates_NN.json`, since 2026-10-25, decision 135; rulebook 2b):
    `update_resources` with `sd_targets` items, `{type: "sd_targets", targetId: <number>, bid}` or
    `{type: "sd_targets", targetId: <number>, state: "paused"}`: the id is a number and the state lowercase, unlike
    Sponsored Products. 100 per file. Read them back with `list_resources sd_targets` and a `campaign_id_filter` (or
    `ad_group_id_filter`): it has no target-id filter.
16. **Product-page base bid** (`9c_placement_shape.json`; decision 140, placements.md "Product-page base bid"): **last**,
    after the keyword and product-target bid files (steps 8 and 14) went out and read back. One `sp_campaigns` item per shaped campaign, in the
    same `optimizations.bidSettings` shape at `SALES_DOWN_ONLY`, every live placement listed. **Write a campaign's shape
    only when every bid and pause row of that campaign read back as written** (the campaign ids are in each row; the bid
    rows carry `shape_row_id`; a keyword left serving, say by a pause that failed, would take the raised modifiers on its
    old bid): over the old base bids the raised modifiers would bid above the plan's price. Skip any campaign with
    a failed or mismatched bid, and say so in the run log; its bids already went out lower, which is safe. Before the
    write, read the campaign live: if its strategy is no longer the row's `strategy_now`, its three placements are no longer the
    row's `modifiers_now`, or a placement the shape does not change differs from the row's `bid_adjustments`, skip it. After it, read back `bidStrategy` and all three modifiers. A skipped
    campaign makes the folder partly applied: record what went out with `applied --rows` (weekly-run.md, "Read back every
    row").

## Shapes that work

- **New B2B exact keyword:** `{"type":"sp_keywords","campaignId":"…","adGroupId":"…","keywordText":"…","matchType":"EXACT","bid":1.2,"state":"ENABLED"}`
- **Campaign update.** Send the complete placement list, or the omitted placements reset to 0:
  `{"type":"sp_campaigns","campaignId":"…","budget":{"budget":10,"budgetType":"DAILY"},"dynamicBidding":{"strategy":"LEGACY_FOR_SALES","placementBidding":[{"placement":"PLACEMENT_TOP","percentage":50}]}}`
  After any `sp_campaigns` update, read `siteRestrictions` back and check it is unchanged (2026-10-21, rulebook 9).
  MarketplaceAdPros can't write it. If an update drops it, stop and have a person restore it in the Ads console: an
  Amazon Business campaign without it serves every shopper.
- **Bidding strategy or placement shape** (MAP's `optimizations` shape; never send `dynamicBidding` with it):
  `{"type":"sp_campaigns","campaignId":"…","optimizations":{"bidSettings":{"bidStrategy":"SALES_DOWN_ONLY","bidAdjustments":{"placementBidAdjustments":[{"placement":"TOP_OF_SEARCH","percentage":42},{"placement":"REST_OF_SEARCH","percentage":12},{"placement":"PRODUCT_PAGE","percentage":0}]}}}}`.
  Every placement the campaign has must be listed (an omitted one resets to 0), and `audienceBidAdjustments` too when it
  has any.
- **Keyword bid:** `{"type":"sp_keywords","keywordId":"…","bid":0.49}`. **Pause:** `{"type":"sp_keywords","keywordId":"…","state":"PAUSED"}`
- **Negative exact (ad-group level):** `{"type":"sp_negative_keywords","campaignId":"…","adGroupId":"…","keywordText":"…","matchType":"EXACT","state":"ENABLED"}`
- **Archive a negative:** `{"type":"sp_negative_keywords","keywordId":"…","state":"ARCHIVED","level":"ad_group"}`
- **Ad group default bid:** `{"type":"sp_ad_groups","adGroupId":"…","defaultBid":0.49}`
- **Price.** `update_listing` with a `purchasable_offer` replace that carries BOTH the `audience: ALL` entry and the
  `B2B` entry:
  - keep `our_price`; change `discounted_price` when the product is on a long-running sale.
  - Run `validation_mode: amazon_preview` first. MAP's local "too many values" warning on the two entries is
    expected; Amazon's VALID is what counts.
  - Verify live with SP-API `amazon_get_competitive_pricing`.

## Reading

| Call | Behaviour |
|---|---|
| `list_resources sp_campaigns` | `name_filter` is a broad match; use `state_filter: "ALL"` to include archived; `campaign_id` takes a list |
| `sp_keywords` | ONE `campaign_id` per call; `keyword_text_filter` is a contains match |
| `sp_ad_groups`, `sp_product_ads` | `campaign_id` takes a list |
| `sp_negative_keywords` | Filter by `ad_group_id`; a `campaign_id` filter pages oddly (empty first page with a next_token) |

**SQL (`run_report_sql`).**
- `sponsored_products_campaigns` works over months.
- `sponsored_products_keywords` works for about 2-day windows filtered by `campaignName LIKE '%ASIN%'`, or for an
  `IN (...)` list of keyword IDs. Wider queries run out of memory.

## Verify after each step

- **Campaigns:** list the touched campaigns (`campaign_id` list, state ALL) and confirm budget, top of search and
  state.
- **Bids and pauses of keywords and targets: read back every row, not a sample** (changed 2026-10-19; it holds for every
  folder). Compare the written rows with `lanes.readback_mismatches`: the snippet is in
  [weekly-run.md](weekly-run.md), "Read back every row". A bid differs by more than $0.005; a pause is confirmed by state
  PAUSED. Any mismatch stops the apply.
- **Negatives:** confirm archived ones are gone (`ad_group_id` + stem).

Report any `failed` count, with the error, before moving to the next step.
