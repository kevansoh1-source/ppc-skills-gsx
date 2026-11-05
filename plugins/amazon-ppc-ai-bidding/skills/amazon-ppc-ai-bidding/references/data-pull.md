# Data pull (one run folder per product per run)

Folder: `runs/<ASIN>-<YYYY-MM-DD>/`, in the session scratchpad or a shared runs folder. `plan.py` reads each file
either as plain JSON or as the tool-result wrapper Claude Code saves big outputs in (`[{"type":"text","text":"…"}]`).

**Saving outputs.**
- **Large outputs:** when the harness saves them to `tool-results/<id>.txt`, copy that file into the run folder
  under the name below. **2026-10-23, Codex or any host without automatic spill:** explicitly save each response
  to that folder before summarizing it; never assume a tool-results file exists. `plan.py` accepts plain JSON,
  `[{"type":"text","text":"<json>"}]`, `{"content":[{"type":"text","text":"<json>"}]}` or
  `{"structuredContent": <payload>}`. Prefer the plain payload; do not save a truncated display of the response.
- **Small outputs:** write the JSON with the Write tool. A MAP or Scale Insights read under about 50,000 characters
  comes back inline, not as a tool-results file (2026-11-04): save that response as it came, in full, under the
  file's name. Never rebuild a file from what you read on screen.
- Don't paste big outputs into context.
- **Read every page.** `get_keyword_performance` and `get_target_performance` page until `oppMeta.has_next_page` is false
  (B0SAMP0001's first pages held 1,111 of 1,773 keyword rows, 2026-11-04). `get_target_performance` with `ad_type="SD"`
  and one ASIN returns about 3,800 rows for the whole account (8 pages at count 500, about 40 Scale Insights units); the
  planner keeps only the product's own rows, but it needs every page to find them.

## When Scale Insights is out of allowance (the backup; Kim, 2026-11-04)

Scale Insights is the default for the reads below. Its MCP allowance is 1,200 units per window (it resets at a set time,
`get_mcp_usage` says when; 15,000 a week), and a product's pull takes about 100 to 180. When it says "MCP usage limit
reached", don't wait: pull from SoldScope and MarketplaceAdPros, and `scripts/report_sources.py` writes the files in the
shapes `plan.py` reads. The run log names the source of each input.

| Instead of | Pull | Then |
|---|---|---|
| `sqp_p*.json` | SoldScope `search_query_performance_export`: `sellerId` `AEXAMPLESELLER`, `marketplace` `US`, `period_type` `weeks`, `group` `keyword`, `asins` [ASIN], `periods` from `python scripts/report_sources.py weeks --through <last Saturday with data>` (13 weeks). Save it as `soldscope_sqp_raw.json` | `python scripts/report_sources.py sqp --asin <ASIN> --run <run> <run>/soldscope_sqp_raw.json` writes `sqp_p1.json`. Last season: the same weeks a year back, `--last-season` |
| `kw_p*.json`, `pt_p*.json` | MAP `run_report_sql` with the SQL `python scripts/report_sources.py sql --asin <ASIN> --kind kw --end <US yesterday> [--campaign-ids <ids named without the ASIN>]` prints, `limit` 1000; again with `--offset 1000` ... while `truncated` is true. Save as `map_kw_raw_p1.json`, `_p2` ... | `python scripts/report_sources.py ads --asin <ASIN> --run <run> --kw <run>/map_kw_raw_p*.json --st <run>/map_st_raw_p*.json --sb-st <run>/map_sb_st_raw_p*.json` writes `kw_p1.json`, `pt_p1.json` and `st_p1.json` |
| `st_p*.json` | The same with `--kind st` (`map_st_raw_p*.json`) and `--kind sb_st` (`map_sb_st_raw_p*.json`) | (the `ads` command above) |

The two match: on B0SAMP0017, Oct 1 to 28, MAP's keyword report (`purchases7d`, `sales7d`) read the same 729 keywords,
$540.71, 774 clicks and 73 orders as Scale Insights' keyword report. SoldScope's SQP is the same Brand Analytics data; its
weeks can be cut a day apart from Scale Insights' (docs/knowledge/soldscope-sqp-fallback-2026-11-04.md). Still from Scale
Insights: `sd_targets_p*.json` (SD targets), `sales_daily.json` (the organic share is then not reported, never a stop) and
product costs. `report_sources.py` refuses to write over a file that is already there: one source per report.

| File | Call | Settings |
|---|---|---|
| `sqp_p1.json`, `sqp_p2.json`, … | Scale Insights `get_search_query_data` | `asin_list=[ASIN]`, `days=90`, `mode="raw"`, `count=100`, `page=1..Meta.total_pages`. 600–750 queries is normal for a bookmark product (7–8 pages) |
| `st_p1.json`, … | Scale Insights `get_search_term_performance` | `asin_list=[ASIN]`, `days=90`, `mode="raw"`, `count=500`, `sort_by="cost"`, pages until `oppMeta.has_next_page` is false |
| `kw_p1.json`, … | Scale Insights `get_keyword_performance` | `asin_list=[ASIN]`, `days=90`, `mode="raw"`, `count=500`, `sort_by="cost"`, `min_spend=0`, all pages |
| `pt_p1.json`, … | Scale Insights `get_target_performance` | `asin_list=[ASIN]`, `ad_type="SP"`, `days=90`, `mode="raw"`, `count=500`, `sort_by="cost"`, all pages. The `asin_list` filter also returns other products' targets; the planner keeps only rows whose campaign name carries the ASIN (rulebook 2b) |
| `suggested_bids.json` | MAP `get_amazon_ads_ad_group_bid_recs` | Legacy query map for the existing rank/harvest calculations: `keywords=[{"text": s, "match_type": "EXACT"}, …]` for every search in `need_suggested_bids.json`, plus relevant harvest candidates. Use the intended product/ad-group context and retain the raw response and date. Save as `{"search": [low, median, high], "_note": "ad group …, date"}`. This map does **not** establish broad/phrase/target recommendation coverage. Since 2026-10-31 (decision 177, rulebook 2i) `need_suggested_bids.json`'s `searches` also holds the exact searches of the validated and launch-test ordinary keywords that bid the suggested mid: read them the same way |
| `suggested_bids_match.json` | MAP `get_amazon_ads_ad_group_bid_recs` | **Not needed since decision 183 (2026-11-04): the mid is for exact keywords only, so `need_suggested_bids.json`'s `keywords` list is empty.** Only if `config.json` `mid_bid.match_types` lists broad or phrase again: the suggested mid's broad and phrase keywords (decision 177, rulebook 2i): every entry of `need_suggested_bids.json`'s `keywords` list, `keywords=[{"text": t, "match_type": "BROAD"}]` (or `"PHRASE"`), on an enabled ad group of the ASIN (the keyword's own when you can). Save as `{"broad": {"text": [low, median, high]}, "phrase": {"text": [low, median, high]}, "_note": "ad group …, date"}`. A keyword whose live read already carries Amazon's recommendation isn't listed. Rate-limited or none after one retry: record it in `bid_sources_tried.json` like the exact searches; the planner then takes SoldScope's middle cost per click for the search (`soldscope_bids.json`), else an estimate |
| `suggested_bids_business.json` | MAP `get_amazon_ads_ad_group_bid_recs` | Business (B2B) invest searches (added 2026-10-21; rulebook 9.7): every search in `need_suggested_bids_business.json`, read in the B2B ad group that file names for it (`campaign_id`, `ad_group_id`: the owner keyword's ad group, else the ad group a new B2B exact keyword goes into, else the B2B ad group that paid most for the search; any enabled B2B ad group of the product when it names none), `keywords=[{"text": s, "match_type": "EXACT"}]`. A B2B auction prices differently (B2B clicks cost $1.63 against $0.87 consumer over the 90 days to 2026-10-21), so a consumer suggestion never stands in for it. Save as `{"search": [low, median, high], "_note": "ad group …, date"}`. **Exit 2:** `plan.py` stops with exit code 2 and writes `need_suggested_bids_business.json` (`{asin, searches: [{search, campaign_id, ad_group_id}], how}`) while a business invest search it will price is missing from this file, as it does with `need_suggested_bids.json` for consumer invest searches; one pull can answer both. A search listed with no median is priced at 1.5 × its breakeven |
| `soldscope_bids.json` | SoldScope `kr_asin_search` then `kr_get_results` (the ASIN's keyword research), or `keyword_research_search_by_keyword` for one query | Only for the searches Amazon gave no suggestion for (decision 106, 2026-10-23), and since decision 177 the suggested mid's keywords Amazon gave none for (exact, broad or phrase: SoldScope's figure is for the search text). Read `cpcMin`, `cpc`, `cpcMax` of the row whose keyword is exactly the search; save as `{"search": [cpcMin, cpc, cpcMax], "_note": "SoldScope job <id>, <date>"}`. A zero or missing `cpc` means none: leave the search out. Never borrow a related query's figure. Keep the raw responses as `soldscope_bid_*.json`. When no Amazon medians exist and its attempt is recorded, complete positive ordered ranges for this product's exact terms also price harvest with the unchanged formula and gate bands; `harvest.bid_source` says `soldscope`. Own CPC/breakeven never synthesizes a low or high for the gate. |
| `bid_sources_tried.json` | (written by the agent) | After Amazon was tried for the searches in `need_suggested_bids.json` (and `need_suggested_bids_business.json`): `{"amazon": "<what happened, SGT time>", "soldscope": "<what happened>"}`. Its presence lets `plan.py` price the searches still missing (rulebook section 2, "When Amazon gives no suggested bid"). Rate limit: MAP can answer a throttle with `isError: false` and text saying "rate limit"; read the text. Wait about 5 minutes, retry once with about a minute between ad-group calls, then stop asking Amazon and move on |
| `campaigns.json` | MAP `list_resources` `sp_campaigns` | `filters={"name_filter": ASIN, "state_filter": "ALL", "max_results": 500}`. Save the raw output. The read carries `siteRestrictions` and `optimizations`: keep every field, never a trimmed copy. The planner reads `siteRestrictions: AMAZON_BUSINESS` to know a business campaign (rulebook 9; 2026-10-21). Required since 2026-10-25: the live inventory reads below go by its campaign ids |
| `recent_kw.json` | MAP `run_report_sql` | SQL below. Save the raw output |
| `radar_p1.json`, … | DataDive `get_rank_radar_data` | `rankRadarId` from the product file, `startDate` = 90 days ago (or the invest start), `endDate` = yesterday, `pageSize=100`, all pages |
| `sales_daily.json` | Scale Insights `get_sales_data` | `asin_list=[ASIN]`, `group_by="day"`, `mode="raw"`, `include_growth=false`, `days=28`, `count=100` (the daily rows page at `count` too: the default 20 returns 20 of 28 days), no `end_date` (Scale Insights then ends at the marketplace's yesterday; an SGT date is often today in the US, and today's figures are incomplete). Added 2026-10-26 (decision 143): the product's organic share (1 − `PPCSales`/`Sales` over 28 days) is reported in the plan summary (it drove the organic-share brake until 2026-10-31, and its `Profits` the efficiency guard; decision 175 dropped both, [rulebook section 2g](rulebook.md)). Without it the share isn't reported, and the plan's `summary.organic.note` says so. A file for another ASIN stops the run. Save the response as it comes; a trailing `account_context` object is fine. PPC sales can exceed sales on a day or a window (attribution lag and halo), so the share is floored at 0 |

**Rank Radar for every invest search (2026-10-26, decision 143).** After `plan.py`, read `summary.organic.radar_missing`:
the invest searches (this run's and the logged ones) with no Rank Radar readings. Add each to the product's radar with
DataDive `add_rank_radar_search_terms` (or `create_rank_radar` when the product has none), within the `get_quota` free
slots and with no approval (decision 105); park one For human item for Kim only when the slots run short. Say how many
were added in the run log. The top-10 rule reads these radars, and so does the stop-loss at months 3/6/9/12 (decision
142). Space the calls about a minute apart (they rate-limit).

## Negative-resource level check (2026-10-24 SGT)

MAP `list_resources sp_campaign_negative_keywords` with a `campaign_id` filter returned rows marked
`level: ad_group` during the readiness audit. Inspect each returned row's actual level and IDs; the resource
name or campaign filter does not establish campaign-level coverage. Read ad-group negatives with
`list_resources sp_negative_keywords`, using `ad_group_id` plus `keyword_text_filter` (a contains/stem filter),
and paginate fully. For a full group check, read all its negatives without the text filter. Keep campaign and
ad-group coverage separate: do not treat the campaign-negative read as proof there are no ad-group negatives,
or these ad-group rows as proof there are no campaign negatives. Sam campaign-level coverage unverified until
the returned evidence establishes it. See [readiness-audit.md](readiness-audit.md) for the read-only SKC check.

## Delivery and recommendation coverage (2026-10-19 SGT)

Also prepare `visibility_inputs.json` using the exact normalized contract in [visibility.md](visibility.md).
This closes the activity-only report gap; it does not replace the legacy rank/harvest map above.

1. **Inventory first.** Read the product's current SP campaigns, ad groups, advertised ASIN assignments and
   keywords/targets with MAP `list_resources`, including all states and every page. Join by stable IDs and verify
   ASIN ownership; a campaign-name match alone is not proof. Keep zero-delivery objects in the normalized inventory.
   A performance report with no row cannot establish that an object is absent or paused.
2. **Daily delivery.** Query the actual available report schema before constructing a read. For SP keywords the
   existing SQL below demonstrates `date`, `keywordId`, `impressions`, `clicks`, `cost` and `purchases7d`. Pull small
   daily/two-day slices, retain zero-spend rows (do **not** use `HAVING SUM(cost) > 0`), and left-join them to inventory.
   A missing day is unknown unless report completeness is established. Keep source dates and attribution maturity.
   Do not invent equivalent target/SB columns; inspect their available schema and normalize supported fields.
3. **Eligible time and blockers.** Use live campaign/ad-group/keyword/product-ad states plus the signed-in SI
   assigned rules/dayparting view. Record approved active hours, schedule overrides, budget exhaustion, buyability,
   inventory and negative/routing checks with evidence. Seven calendar days are not seven verified eligible days.
   If eligibility cannot be established, mark it unknown rather than treating every zero as bid starvation.
4. **Recommendations for each candidate.** Read `get_amazon_ads_ad_group_bid_recs` using each keyword's real match
   type and campaign/ad-group context, batching only compatible requests. Save the raw low/median/high values,
   requested text, match type, IDs, ad product and read date in the normalized input. A single exact query map from
   another group is not evidence of that broad/phrase keyword's recommendation. For new exact tests, identify the
   proposed exact context explicitly. Unsupported recommendations remain unavailable; do not substitute SP keyword
   recommendations for SB, auto or product targets.
5. **Observed delivery and economics.** Include actual CPC, qualified-query evidence and attainable sample goals.
   Do not decide success from an absolute impression count shared across all queries. Refresh economics at the
   current shopper price. Every proposed learning test needs concrete target-specific limits before it can be
   reviewed for execution; the input may leave those missing, which produces a hold/request rather than an increase.

Keep the two-day **recent spend safety sweep** below unchanged: its positive-spend filter is intentional for that
purpose, but it must not be reused as the delivery inventory. No automatic read or browser action is performed by
the local normalization/review code; the agent gathers and verifies these inputs on each run.

**Live inventory** (added 2026-10-25, Kim, decision 135: "we'll price every single keywords now, leaving none behind
with the best data available"; rulebook 2c). Scale Insights reports only keywords and targets with a 90-day row, so the
ones that barely ran (an hour a day under an old schedule) never reached the plan and kept their old bids. Every run reads
the live lists too. `plan.py` stops and writes `need_live_inventory.json` while one is missing, with the campaign id groups
to read (100 ids a group, from `campaigns.json`'s enabled campaigns):

| File | Call | Settings |
|---|---|---|
| `live_keywords_p1.json`, … | MAP `list_resources` `sp_keywords`, once per id group | `filters={"campaign_id": "<id,id,…>", "state_filter": "ENABLED,PAUSED", "max_results": 1000}`, every page (`next_token`). Save the raw output |
| `live_targets_p1.json`, … | MAP `list_resources` `sp_targets`, once per id group | The same filters. Auto targets come back with `expressionType: AUTO` (close match, loose match, substitutes, complements) |
| `sd_targets_p1.json`, … | Scale Insights `get_target_performance` | `asin_list=[ASIN]`, `ad_type="SD"`, `days=90`, `mode="raw"`, `count=500`, `sort_by="cost"`, all pages. As with `pt`, the planner keeps only rows whose campaign name carries the ASIN |
| `sd_campaigns_p1.json`, … | MAP `list_resources` `sd_campaigns` | `filters={"campaign_id_filter": "<id,id,…>"}` for the ids `need_live_inventory.json` lists after the SD pull (the SD campaigns its targets name): the planner prices a target only in an enabled campaign that bids per click (`costType` cpc; vCPM is per thousand impressions) |

When a read can't be made (MAP down, a rate limit that won't clear), plan with `--partial-inventory "<why>"`: the run
goes on with the rows Scale Insights reports, `summary.inventory.partial_reason` records why, and the next run reads them.

**Full coverage reads** (Kim, 2026-10-27, decision 155; all MAP, read only). The coverage ledger names any of these the
run didn't have in `summary.coverage.reads_missing`:

| File | Call | Settings |
|---|---|---|
| `live_ad_groups_p1.json`, … | `list_resources` `sp_ad_groups` | `filters={"campaign_id": "<one group of need_live_inventory's ids>", "state_filter": "ENABLED,PAUSED", "max_results": 500}`, every page. The ad-group default bids are priced from it |
| `shared_campaigns.json` | `list_resources` `sp_campaigns` | `filters={"campaign_id": "<the ids the product file's shared_campaigns lists>", "state_filter": "ENABLED,PAUSED"}`. Only when the product file lists shared campaigns; read it before the live keyword reads, so their ids join the groups |
| `si_changes_p1.json`, … (morning routine, not per product) | Scale Insights `get_change_history` | `source="manual"`, `mode="raw"`, `days=2`, `count=100`, every page; then `python scripts/si_changes.py <pages>` |

With `inventory.paused` the live keyword and target reads cover the paused campaigns too (need_live_inventory.json's
groups hold both).

**Campaigns by product ad** (Kim, 2026-10-27, decision 156: "check to see if the new skill covers every single campaign
and every single keyword, product targeting on SP, SB, SD for the ASIN, don't leave any out"). Until then a campaign was
the product's only when its name carried the ASIN, so its single-ASIN campaigns named without it (the "Auto - $0.65/$0.30
down only" ones: $257 in the 30 days to Oct 25, 2026) were never priced. Every run now reads the campaigns the product's own
ads served in, through MAP `run_report_sql`, before `campaigns.json`'s groups are built (`inventory.ad_campaigns`):

```sql
-- ad_campaigns_p1.json: Sponsored Products
WITH mine AS (SELECT DISTINCT campaignId FROM sponsored_products_product_ads
              WHERE advertisedAsin = '<ASIN>' AND date BETWEEN DATE '<90 days ago>' AND DATE '<yesterday>')
SELECT 'SP' AS ad_type, CAST(p.campaignId AS VARCHAR) AS campaignId, MAX(p.campaignName) AS campaignName,
       string_agg(DISTINCT p.advertisedAsin, ',' ORDER BY p.advertisedAsin) AS asins, ROUND(SUM(p.cost), 2) AS spend90
FROM sponsored_products_product_ads p JOIN mine ON mine.campaignId = p.campaignId
WHERE p.date BETWEEN DATE '<90 days ago>' AND DATE '<yesterday>'
GROUP BY p.campaignId ORDER BY spend90 DESC

-- ad_campaigns_p2.json: Sponsored Display (the same, on promotedAsin)
WITH mine AS (SELECT DISTINCT campaignId FROM sponsored_display_product_ads
              WHERE promotedAsin = '<ASIN>' AND date BETWEEN DATE '<90 days ago>' AND DATE '<yesterday>')
SELECT 'SD' AS ad_type, CAST(p.campaignId AS VARCHAR) AS campaignId, MAX(p.campaignName) AS campaignName,
       string_agg(DISTINCT p.promotedAsin, ',' ORDER BY p.promotedAsin) AS asins, ROUND(SUM(p.cost), 2) AS spend90
FROM sponsored_display_product_ads p JOIN mine ON mine.campaignId = p.campaignId
WHERE p.date BETWEEN DATE '<90 days ago>' AND DATE '<yesterday>'
GROUP BY p.campaignId ORDER BY spend90 DESC
```

Pass `account_ids=["9000000000000003"]` (the US profile). What the planner does with each row (`plan.load_ad_campaigns`):

- **Several ASINs** (`asins` holds more than this one): a product collection or cross-selling campaign, kept that way on
  purpose (Kim, 2026-10-27: "we can leave out campaigns with multiple ASINs"). It is left out of the pricing, even
  when its name carries the ASIN, and listed in `summary.campaign_scope.multi` and the coverage ledger (`multi_asin`).
- **This ASIN alone, name without it**: joins the product's campaigns. `plan.py` then asks for its live record
  (`need_live_inventory.json` `own_campaigns`): `list_resources` `sp_campaigns`,
  `filters={"campaign_id": "<the ids>", "state_filter": "ALL"}`, saved as `own_campaigns.json`. Its keywords and targets
  come in with the live keyword and target reads, by campaign id.
- **Every single-ASIN SD campaign** (named or not): its live targets are read by id (`need_live_inventory.json`
  `live_sd_targets`): `list_resources` `sd_targets`, `filters={"campaign_id_filter": "<one group>"}`, saved as
  `live_sd_targets_p1.json`, …. A live target with no 90-day row in Scale Insights is priced like a Sponsored Products one
  with no clicks: capped, never raised.

A campaign with no impression in the 90 days has no product-ad row, so it is found by its name alone, as before; it
hasn't spent either. Sponsored Brands campaigns are still found by name (`sb_campaigns` `name_filter`), and a product
collection or store spotlight one is told by its name (`sb_video.multi_asin_markers`).

**Sponsored Brands video** (added 2026-10-18; all MAP, read only):

| File | Call | Settings |
|---|---|---|
| `sb_campaigns_p1.json`, `_p2`, … | `list_resources` `sb_campaigns` | `filters={"name_filter": ASIN, "state_filter": "ENABLED,PAUSED", "max_results": 100}`, every page (`next_token`). A bookmark product has about 180 |
| `sb_keywords_p1.json`, … | `list_resources` `sb_keywords`, once per id group in `need_sb_keywords.json` (the product's consumer SB campaigns, the AI's video series and the older ones, 20 ids per group; since 2026-10-25 the older ones are priced too, cut only, rulebook 5b) | `filters={"campaign_id": "<id,id,…>", "max_results": 500}`, every page. Don't use `keyword_text_filter` to check coverage: on 2026-10-18 it missed Scenery's live "christian bookmarks" exact keyword |
| `sb_targets_p1.json`, … | `list_resources` `sb_targets`, once per id group in `need_sb_keywords.json` (decision 155, 2026-10-27: SB product and category targets are priced) | `filters={"campaign_id": "<id,id,…>", "max_results": 500}`, every page |
| `sb_themes_p1.json`, … | `list_resources` `sb_themes`, once per id group in `need_sb_keywords.json` (decision 156, 2026-10-27: SB theme targets, "keywords related to your brand" and "... to your landing pages", are priced, cut only; $68 in the 30 days to Oct 25, 2026) | `filters={"campaign_id": "<id,id,…>", "max_results": 500}`, every page. Its results are the keyword report's THEME rows (`sb_kw_perf.json`: there the keywordId is the themeId) |
| `sb_campaign_days.json` (or `_p2` … pages) | `run_report_sql` (decision 175, 2026-10-31: the weekly leak check reads Sponsored Brands too) | The product's SB campaigns by day, the 15 days to yesterday, `limit` 1000: `SELECT campaignId AS campaign_id, any_value(campaignName) AS campaign, date, SUM(cost) AS cost, MAX(campaignBudgetAmount) AS budget, SUM(sales) AS sales, SUM(purchases) AS orders, SUM(clicks) AS clicks FROM sponsored_brands_campaigns WHERE date BETWEEN DATE '<today-15>' AND DATE '<today-1>' AND campaignName LIKE '%<ASIN>%' GROUP BY campaignId, date ORDER BY campaignId, date LIMIT 1000 OFFSET <0, 1000, …>`. SB has 14-day attribution only (unsuffixed `sales`, `purchases`); legacy SB campaigns come from Amazon's legacy report and keep about 60 days. The planner keeps only the product's own SB campaigns (`sb_campaigns`, collections left out) and leaves out the SB rank campaigns. Without it the leak check reads Sponsored Products only and `summary.organic.note` says so; never a stop |
| `sb_kw_perf.json` | `run_report_sql` | SQL below, over all of the product's SB campaigns (since decision 155 the audience and B2B ones too). A target's rows are in it: on them the report's keywordId is the targetId |

```sql
SELECT keywordId, keywordText, matchType, campaignId, SUM(clicks) AS clicks, SUM(purchases) AS purchases,
       ROUND(SUM(cost),2) AS cost, ROUND(SUM(sales),2) AS sales
FROM sponsored_brands_keywords
WHERE date >= DATE '<90 days ago>' AND campaignId IN (<the product's consumer SB campaign ids>)
GROUP BY keywordId, keywordText, matchType, campaignId
```

Run the planner once after `sb_campaigns`: it writes `need_sb_keywords.json` with the id groups. The Sponsored Brands
keyword report has no bid column, so live bids come from `list_resources`. These reads are required (decision 191,
config `coverage.required_reads`): without them the planner stops with exit 2, whatever flag it is given, so Sponsored
Products and Sponsored Brands are always priced in the same run.

Recent keyword spend SQL. Keep the window to 2 days: longer windows on this table run out of memory.

```sql
SELECT keywordId, keyword, matchType, campaignName, ROUND(SUM(cost),2) AS cost, SUM(clicks) AS clk,
       SUM(impressions) AS imp, SUM(purchases7d) AS ord, MAX(keywordBid) AS bid
FROM sponsored_products_keywords
WHERE date BETWEEN DATE '<2 days ago>' AND DATE '<yesterday>' AND campaignName LIKE '%<ASIN>%'
GROUP BY keywordId, keyword, matchType, campaignName HAVING SUM(cost) > 0 ORDER BY cost DESC
```

## Monthly: the B2B pool's prior (2026-10-21)

Business keywords are priced on the B2B campaigns' pooled conversion, shrunk by the 10-click prior toward one
account-wide number: `config.json` `business.pool_prior_cvr` (0.346 as of 2026-10-21: 3,353 orders on 9,685 clicks, 90
days). Refresh it once a month, in the record step, not every run. First due 2026-11-21 (docs/open-items.md).

**One source of record:** MarketplaceAdPros `run_report_sql` over `sponsored_products_campaigns`, for the campaigns step
1 names, exactly as below: not the search-term or keyword tables, not Scale Insights. One table every month, so the
months compare. `business.pool_prior_source` in `config.json` says the same. (The 2026-10-21 figure came from the
fold's account pull, docs/knowledge/amc-audiences-2026-10-21.md section 4; from the first refresh on, this recipe is
the only source.)

1. **The B2B campaigns.** MAP `list_resources` `sp_campaigns`, `filters={"state_filter": "ALL", "max_results": 500}`,
   every page, the whole account (no name filter): keep the campaigns whose `siteRestrictions` include
   `AMAZON_BUSINESS`. The flag is the truth, not the "B2B" in the name.
2. **Their 90 days:** the 90 days to the day before `pool_prior_as_of` (the run date). MAP `run_report_sql`, over
   those campaign ids (check the column names with `describe_report_tables` first; orders are the 7-day attribution,
   as in the keyword SQL above):

   ```sql
   SELECT COUNT(DISTINCT campaignId) AS campaigns, SUM(clicks) AS clicks, SUM(purchases7d) AS orders,
          ROUND(SUM(purchases7d) / NULLIF(SUM(clicks), 0), 4) AS cvr
   FROM sponsored_products_campaigns
   WHERE date BETWEEN DATE '<90 days before pool_prior_as_of>' AND DATE '<the day before pool_prior_as_of>'
     AND campaignId IN (<the B2B campaign ids>)
   ```
3. **Record.** `cvr` goes to `business.pool_prior_cvr`, the run date to `pool_prior_as_of`. It is a config change, so
   Kim signs it off; the run log says the figure, its window, the campaign, click and order counts. Sam the open
   item done and add the next month's. Without the number the planner falls back to the product's consumer ad
   conversion and says so in `summary.business.pool_prior`.

## Inputs for the lanes (2026-10-19)

`plan.py` reads these optional files to decide who has to approve each change ([rulebook.md](rulebook.md) section 7).
Save each as plain JSON in the run folder. Say where each figure came from, and its date, in the run log.

| File | Contents | What it does |
|---|---|---|
| `inventory_cover.json` | `{"cover_days": 21}`: days of stock cover, worked out the way the book owner does the stock check | 14 days or fewer: inventory alert for manual stock management; Auto eligibility is unchanged (Kim, 2026-10-24) |
| `price_change.json` | `{"days_since": 5}`: days since the listing price last changed (for example from MAP `get_listing_change_history`) | Not read since decision 168 (2026-10-29): a recent price change holds nothing. Until then, under 14 days held every change |
| `soldscope_volume.json` | `{"<search>": monthly searches}`: SoldScope's volume for invest searches that SQP has no clicks for | Feeds that search's investment band. Since 2026-10-22 it is also the volume of a search that neither SQP nor the launch list has, scaled to the product's SQP window (`monthly x window_days / 30`): the 150-search gate and the opportunity ordering read it (rulebook 10.3, item 3) |
| `niche_keywords.json` | DataDive `get_niche_keywords` for the product's niche, as the tool returned it ("Launch list" below) | Optional. The "unlisted" head-term flag checks a search against its keywords (rulebook 10.3, item 4). The same file builds the launch list |
| `si_blacklist.json` | `{"NegativeExactList": [...], "NegativePhraseList": [...], "ExactWhiteList": [...], "PhraseWhiteList": [...], "_read": "<when>"}`: the product's Scale Insights blacklist page (scale-insights-playbook.md, "Blacklist rescue") | The blacklist rescue (Kim, 2026-10-21): any entry that blocks an Invest or Prove-first search becomes a step-95 "Scale Insights setup" row for a person, and `summary.blacklist_rescue` says it was checked. Needed every run that has invest searches |
| `reviews.json` | `{"asin", "saved_at", "entries"}`, saved by `python scripts/dashboard.py reviews --asin <ASIN> --save <run>/reviews.json`. Don't write it by hand | The team's decisions: every decline becomes a lock. **Required** whenever the product file holds any bids item, whatever its status. It must be for this ASIN and saved no more than a day before the run, or `plan.py` refuses to plan. `--no-reviews "<why>"` plans without it (every change then goes to a person) |

## The listing and the daily clicks (For Growth, 2026-10-22)

Wrong-size keyword pauses also require a fresh raw listing read and `listing_size_verification.json` before
they can enter Auto. Follow [live-size-pauses.md](live-size-pauses.md); the For Growth normalized `listing.json`
alone does not establish this evidence. Unknown or ambiguous sizes retain their existing hold.

Two optional files for the For Growth step of the run ([for-growth.md](for-growth.md)); nothing else reads them. Both
were worked out against live pulls on 2026-10-22. `plan.py` stops if either names another ASIN.

| File | Call | Settings |
|---|---|---|
| `listing.json` | MAP `get_selling_partner_listings` | `account_id` = the "YourBrand US" Selling Partner account `00000000-0000-4000-8000-900000000004` (the US row, not BR), `seller_skus` = the product's SKU, `include_data: ["attributes"]`. Save the fields below as plain JSON |
| `clicks_daily.json` | MAP `run_report_sql` | `report_types: ["sponsored_products_product_ads"]`, `account_ids: ["9000000000000003"]` (the US profile), `limit: 100` (the call returns 50 rows by default, and 90 days can hold 90), the SQL below. Save the rows as plain JSON |

**`listing.json`** is `{asin, read_at, source, title, highlight, bullets, backend}`:
- `read_at` is the read time in SGT; `source` says the call (for example `MAP get_selling_partner_listings, attributes`).
- `title` is the listing title.
- `highlight` is `attributes.title_differentiation`. It is **not** the part of `item_name` after `|`: that was the
  launch design's guess, and on a live read the highlight is its own attribute.
- `bullets` is the list of `attributes.bullet_point[].value`, in order.
- `backend` is `attributes.generic_keyword`. This call does read it (the catalog-item read the launch design named does
  not). `null` when the listing has none; the block's Notes then say the backend was not readable.

Without it the item is weave-ins only, every `in` row sits today as unknown, and no pass can close (the AI's close
compares this file with the item's snapshot). Pull it every run. The close reads only the title, the highlight and the
bullets.

**`clicks_daily.json`** is `{asin, since, through, source, rows: [{date, clicks}]}`: the product's daily ad clicks, 90 days
back. It is needed only while the product file holds no `growth.anchor`: the anchor's first ad click is its first row with
1 or more clicks.

```sql
SELECT advertisedAsin AS asin, date, SUM(clicks) AS clicks
FROM sponsored_products_product_ads
WHERE advertisedAsin = '<ASIN>' AND date >= '<since>'
GROUP BY advertisedAsin, date ORDER BY date
```

- `since` is 90 days before the run date, `through` the last date in the pull. Rows exist only for days with ad data.
- **A first click on `since` itself means the real first click lies before the series**, so it is not counted and the
  launch date stands (an older product is not anchored at the start of the pull).

## Launch list (2026-10-22)

Built when a product enters the launch stage, once its onboarding person has the Monday board's launch date. The weekly
run reads the finished `launch` block from the product file, not these pulls. Build it again only when the niche is dived
again or the research sheet changes, and on the Day-1 check, once the harvest ad group exists, to add Amazon's
recommendations (docs/superpowers/specs/2026-10-21-keyword-selection-by-data-stage-design.md, section 4.3).

1. **Pull the niche.** DataDive `get_niche_keywords` on the niche the Monday "1st Datadive" link names. Save the
   response as it came as `<run>/niche_keywords.json`. It carries no niche id: take the id from the link (for the gel pens,
   `PCAEwf4c8H`) and pass it as `--niche-id`.
2. **Pull Amazon's recommendations** (the Day-1 check; skip before the harvest ad group exists). MarketplaceAdPros
   `get_amazon_ads_ad_group_keyword_recs` on the product's harvest ad group. Save it as `<run>/keyword_recs.json`.
3. **Build the block** (the product file must exist, so the negation can read its `relevance` block; without it the output
   says Amazon's additions were not checked):
   `python scripts/launch_list.py --asin <ASIN> --niche <run>/niche_keywords.json --niche-id <id>
   [--recs <run>/keyword_recs.json] [--extra "search:volume|search:volume"] --today <YYYY-MM-DD> --out <run>/launch_block.json`
   - It prints the table (search, volume, relevancy, score, set, and a note for each fold and each one-word head), the
     left-out searches with their reasons, and the proposed roots. It writes only `--out`, never the product file.
   - Order: volume x relevancy, highest first. Close variants (plurals, spacing, word order) fold into the spelling with the
     higher score. Under `launch.min_relevancy` (0.5) a search is left out. The median set is the first
     `launch.rank_count` (5) with two or more tokens; everything else listed is `shared`, one-word heads included.
     Amazon's additions (impression rank within `launch.amazon_top_rank`, 20, two or more tokens, not already listed or left
     out, not negated) come last at `amazon`, with no volume, relevancy or score.
   - `--extra` is the research sheet's extra searches. They have no DataDive relevancy, so each scores at its volume
     alone and competes like any row. Name the sheet and its tab in the run log.
   - Read the roots before trusting them. `launch.roots` are the words every listed search at relevancy 0.9 or more shares;
     the script proposes them, the onboarding person confirms. Where the niche splits a word (the gel pens' niche has
     "colored" and "colorful" rows at 0.923, so on 2026-10-22 it proposed `pens` alone), rerun with `--roots "pens|colored"`
     or edit the block.
4. **Paste.** Once the person has set `date` (the launch date from the Monday board) and confirmed `roots`, paste the block
   from `<run>/launch_block.json` into the product file as `"launch"`. `qualifiers` stays `[]` until someone enters the
   research sheet's modifiers. The run log says the niche id, the dive date, the read date and who confirmed the roots.

Worked on the gel pens (B0SAMP0012, niche `PCAEwf4c8H` dived 2026-08-19, Amazon's recommendations pulled 2026-10-22, a dry
run that wrote nothing to the product file): 121 niche searches became 80 listed, 19 folded into those and 22 left out
under 0.5; 8 of Amazon's 29 ranked recommendations joined (a ninth, a search the niche left out, no longer does). The
median set was colorful pens, pens colored, colored gel pens, colored ink pens and colorful gel pens. The real niche's median
set and roots differ from the hand-made example in the design's section 4.3 (there the fifth median search is `colored pens
for note taking` and the roots are `pens` with `colored`/`colorful`), so the person confirms both.

## Seasonal products: SoldScope weekly volume (2026-10-21)

Pulled when a seasonal product's `season` block is built: before its wake, and again at each season review for next
year. Not every week: the weekly run reads the block's dates, not SoldScope.

1. **Pick the searches.**
   - The rank searches: the 3 or 4 head searches of the season, the ones a rank build would invest in.
   - The evergreen searches, if any: they stay on outside the season (for example "fall stickers" on a Thanksgiving product).
2. **Pull** SoldScope `common_search_volume_batch` with `marketplace="US"` and up to 100 `keywords`. One call returns about
   3 years of weekly searches per keyword. The output is large: copy the saved `tool-results/<id>.txt` into the run folder
   as `soldscope_weekly.json`.
3. **Build the block:**
   `python scripts/season.py block --asin <ASIN> --volume <run>/soldscope_weekly.json --holiday thanksgiving --rank "a|b|c"
   [--evergreen "x|y"] [--index 0.9] [--set last_mile=YYYY-MM-DD] --out <run>/season_block.json`
   - It prints the proposed block and writes nothing to the product file.
   - The payback test needs `--index`, a person's judgement of the listing's conversion against the market. Without
     it the block has no rank build until someone decides it with `--rank-build yes|no --by "<who, when>"`.
4. **Approve, then record.** The book owner approves the dates (Lee did until 2026-10-22) and Kim any rank build.
   Then paste the block into the product file as `"season"`, and add its dated steps to the product's open items:
   `python scripts/season.py items --asin <ASIN> --run-id <id> --approval "<who, when: words>"`.

- **For a product whose Auto lane is on, a missing `inventory_cover.json` stops the plan** (fix E6; decision 168): plan.py
  exits with "Nothing planned: the inventory cover file is missing ... save inventory_cover.json ...". Supply it for every
  such product. `price_change.json` is no longer needed (decision 168). In shadow a missing file is fine (the check only fires on a file that
  is there), but say the gap in the run log: it is not an all-clear.
- **An inventory cover file that is there but unreadable** (no `cover_days` number) stops the plan the same way.
- **SQP: plan on the newest pages Scale Insights has, however old** (Kim, 2026-10-30, decision 172: "just take the
  latest SQP data that is available and use it"). Pull the pages once at the start of the run and go on; never wait for a
  newer week. `summary[0].sqp_age_days` (from `Meta.data_through`, the oldest page) says how old they were: write it in the
  run log. Until decision 172, SQP over 10 days old stopped an Auto product's plan (decision 168).
- **A seasonal product (a `season` block) also reads last season's SQP** (decision 172: "use last season's sqp"): save
  `last_season_sqp_p1.json`, `_p2` ... from Scale Insights `get_search_query_data` with `asin_list=[ASIN]`, `mode="raw"`,
  `count=100`, all pages, `start_date` = this run's date one year earlier and `end_date` = last year's holiday from the
  season block (at most 90 days; if longer, end 90 days after the start). The planner adds last season's clicks and
  purchases (ours and the market's) to this season's for every search this season shows, and prices each search on the
  total (`price_basis` "SQP + last season"); volume and organic stay this season's. A listing that wasn't live last season
  has no pages: skip the file. The name must not start with `sqp`: the planner would read it as this season's.
- The files are named `inventory_cover.json` and not `stock.json` on purpose: the planner's `st*` glob for search-term
  pages would have picked up `stock.json`.

## The planner's modules (2026-10-19)

`plan.py` calls these from the same `scripts/` folder. All are standard library only. The tests are `test_plan_lanes.py`, `test_lanes.py` and `test_evidence.py`.

| Module | What it holds |
|---|---|
| `plan_lanes.py` | `plan.py`'s lanes step (its section 6): runs the rules over a whole plan; keeps the running totals (band left, invest spend planned, raises left); groups a promotion with its bundle; reads the locks; prices the bands; stamps `apply_after` |
| `lanes.py` | The rules for one change (`classify`), Kim's ladder, a search's band, locks, any-day execution compatibility (`us_write_window_open`), `readback_mismatches` and the 24-hour `spend_check` ([weekly-run.md](weekly-run.md)) |
| `evidence.py` | How sure we are a search beats the market (`p_beats`, `p_below`), `opportunity`, `monthly_searches` and the plain words for them |
| `placement_inputs.py` | Builds `placement_inputs.json` (placements.md) from three MAP reads: `sql` prints the placement report's SQL with its windows; `build` joins the saved report, `campaigns.json` and `live_product_ads_p*.json`, and stops on a truncated report or an enabled campaign with no product ad read (since 2026-10-26, decision 140) |
| `organic_share.py` | The organic share, the top-10 rule and the weekly leak check (decision 143, 2026-10-26; reshaped 2026-10-31, decision 175): reads `sales_daily.json` (`load_sales`), the product's organic share (`product_share`, reported only), the leak check's reading over the ordinary campaigns' settled `campaign_days.json` and `sb_campaign_days.json` rows (`leak_reading`, by channel) and the top-10 searches from Rank Radar or SQP (`top10_searches`). Settings: config.json `organic_share` |
| `searchtext.py` | `norm`, the one normal form for a search or keyword, so the same search matches across reports. `plan.py` re-exports it |

`human_review.py` builds the weekly Bids item from `plan.json`, and `dashboard.py` holds the commands that read and write the
team's decisions ([dashboard.md](dashboard.md)).

## Economics

**Placement recommendations:** also pull mature campaign-placement reports, current campaign
settings and current product ads, then save `placement_inputs.json` as specified in
[placements.md](placements.md). This is required for recommendations in every routine sweep, and since 2026-10-26
(decision 140) for the product-page base bid and the Auto down-only rows: build it every run, with
`python scripts/placement_inputs.py`. Missing data produces an explicit hold; it never falls back to an
automatic TOS boost.

1. `python scripts/placement_inputs.py sql --asin <ASIN> --as-of <SGT date>` prints the SQL. Run it with MAP
   `run_report_sql`, `integration_ids: ["<amazon_ads.integration_id>"]`, `limit: 1000`, and save the whole response as
   `<run>/placement_report.json`. A product with more than about 330 campaigns with placement rows would be truncated:
   the build refuses it, so split the SQL by campaign id.
2. Read the product ads of `campaigns.json`'s enabled campaigns: MAP `list_resources` `sp_product_ads`,
   `filters={"campaign_id": "<id,id,…>", "max_results": 1000}`, 100 ids a call (the same groups as the live keywords),
   every page. Save each as `live_product_ads_p1.json`, `_p2`, ….
3. `python scripts/placement_inputs.py build --asin <ASIN> --run <run> --as-of <SGT date>` writes
   `placement_inputs.json`. If it lists `missing` campaigns, read their product ads and build again.

Read `get_product_metadata` (`asin_list=[ASIN]`): selling price, UnitProfit, BreakEvenAcosPercent.

- If the price or costs moved since `economics_as_of`, update `profit_per_unit` in the product file **before**
  planning. Every breakeven bid depends on it.
- SI's breakeven uses the configured selling price, not the average selling price. During a sale, compute profit
  at the price shoppers actually pay.
- **Referral override (2026-10-26, decision 136).** SI's referral rate is read-only (it comes from Amazon) and can be
  wrong (5% or 15% where Amazon charged about 9-10%). When the product file has `referral_override`, a refresh sets
  `profit_per_unit` = SI UnitProfit − (override `pct` − SI ReferralPercent)/100 × the price shoppers pay, and never
  takes SI's UnitProfit as it is. Update the block's `si_pct`, `price` and `si_unit_profit` with it. Keep the block even
  when SI's rate comes close: since decision 169 it holds the settled rate the planner reads.

### Referral fee (every run, Kim, 2026-10-29, decision 169: "yes, auto-read the referral fee")

Amazon's list rate for our stationery is 15% (Office Products, the Fee Preview report), but the settlement report has shown
10% and 5% on real orders, a reduction that can end. So every run reads what Amazon actually deducted, and `plan.py` prices
on it (`scripts/referral.py`, config.json `referral`):

1. Print the SQL: `python scripts/referral.py --sku <the product file's sku> --today <SGT date>` (Order rows for the SKU
   on Amazon.com posted in the last 14 days, one row: units, principal, commission).
2. Run it with MAP `run_report_sql` (`platform` "selling_partner", `limit` 1000) and save the result as `settlement.json`
   (any shape: MAP's `{"data": [...]}` or the text wrapper).
3. A product with no `referral_override` block yet also needs `product_metadata.json` once (Scale Insights
   `get_product_metadata` `asin_list=[ASIN]`): the rate its UnitProfit carries.

With 10 or more units settled (`referral.min_units`), the rate is commission ÷ principal. `plan.py` moves `profit_per_unit`
by (old rate − new rate)/100 × `price`, writes the product file before pricing, and records the rate, its window, its units
and the previous rate in `referral_override` and in the run summary (`summary[0].referral`). When the profit moves, the
Slack message and the run log say so, for example "referral fee now 15.0% (was 9.94%): profit $3.01 -> $2.61". Under 10
units the stored rate stands (the block's, else Scale Insights'). Without `settlement.json` the run stops and
`need_settlement.json` names the read. The monthly recheck is gone: every run is the recheck.

## Notes from the pilot

- **Search-term report:** covers SP and SB rows. The planner uses all of them for conversion, and only SP rows for
  funnel negatives.
- **Keyword report:** only lists keywords with activity in the window. The campaign list/recent sweep catch some
  omissions but do not provide a full idle-keyword inventory. The inventory-first delivery pull above is required
  to evaluate keywords that never received impressions or spend.
- **SQP lag:** data runs about one week behind (`Meta.data_through`). Note the date in the run log.
