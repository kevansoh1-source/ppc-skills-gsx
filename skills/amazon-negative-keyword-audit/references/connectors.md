# Connectors and exact calls: amazon-negative-keyword-audit

MCP tool prefixes differ between installs: find tools by function name. Behaviours below were
confirmed on a live US seller account in 2026.

## Account
- MarketplaceAdPros: `list_amazon_ads_integrations` gives the `integration_id`;
  `list_amazon_ads_integration_accounts` gives the `account_id`. The profile list can also hold
  other marketplaces and agency/attribution profiles: pick the **seller** profile for the
  marketplace being audited (US = `ATVPDKIKX0DER`).
- Never hardcode these in a shared file you publish; keep them in the user's own notes.

## 0. Fingerprints: cache, don't re-derive
`data/fingerprints.json`, keyed by ASIN (start from `data/fingerprints.example.json`). Read first;
derive only on a miss (`get_product_metadata` → SP-API `get_product_details` /
`get_selling_partner_catalog_item` if thin → product-page read for format claims), then write back.

## 1–2. Pooled scope + waste + converters (run_report_sql)

⚠️ **Never raw-JOIN `search_terms` to `product_ads`.** An ad group with N product ads fans out
every search-term row N times: 30 to 100 times inflation on a real run (one term read 931 clicks
against a true 11). A **DISTINCT subquery is a semi-join** and is safe:

```sql
-- SP waste, pooled across the batch, 7d + 30d in one pass
SELECT pa.advertisedAsin AS asin, st.searchTerm,
       SUM(st.clicks)                                           AS clicks_30d,
       SUM(st.cost)                                             AS spend_30d,
       SUM(CASE WHEN st.date >= '<7d>'  THEN st.clicks END)     AS clicks_7d,
       SUM(CASE WHEN st.date >= '<7d>'  THEN st.cost   END)     AS spend_7d,
       SUM(st.purchases14d)                                     AS orders_30d
FROM sponsored_products_search_terms st
JOIN (SELECT DISTINCT advertisedAsin, campaignId
      FROM sponsored_products_product_ads
      WHERE advertisedAsin IN (<batch>) AND date >= '<30d>'
        AND campaignId NOT IN (<multi-ASIN campaign ids>)) pa
  ON st.campaignId = pa.campaignId
WHERE st.date >= '<30d>'
GROUP BY 1, 2
HAVING SUM(st.clicks) > 0
-- split locally: orders_30d = 0 → waste, >= 1 → converter shield
```

- **⚠️ The multi-ASIN pre-check is a FILTER, not a warning.** A semi-join still hands a shared
  campaign's whole search-term list to every ASIN in it. Recompute per batch and feed the ids
  into the scope subquery:
  ```sql
  SELECT campaignId, COUNT(DISTINCT advertisedAsin) AS n_asins
  FROM sponsored_products_product_ads
  WHERE date >= '<30d>' AND campaignId IN (
    SELECT DISTINCT campaignId FROM sponsored_products_product_ads
    WHERE advertisedAsin IN (<batch>) AND date >= '<30d>')
  GROUP BY 1 HAVING COUNT(DISTINCT advertisedAsin) > 1
  ```
- **Converter shield:** drop the 0-orders `HAVING`, return `orders_30d`, and split waste (`= 0`)
  from converters (`>= 1`) locally: one pull per chunk instead of two, and the shield covers the
  same SP+SB scope as the waste list.
- **SB:** `sponsored_brands_search_terms`; the orders column is `purchases` (SP is
  `purchases14d`). If SB campaign names carry the ASIN:
  `regexp_extract(campaignName, 'B0[0-9A-Z]{8}')`. SP campaign names can be wrong or missing the
  ASIN: trust `advertisedAsin` there.
- **Row cap: `run_report_sql` returns at most 1000 rows.** Chunk the ASIN list.
- **Large results.** Some hosts save oversized results to a file and return its path (it can look
  like an error; it isn't). Parse locally and print only the answer. On hosts without that, save
  each response to a run folder yourself; don't pad SQL to force a feature the host lacks. The
  payload may arrive wrapped (`[{"type":"text","text":"<json>"}]`,
  `{"content":[{"type":"text","text":"<json>"}]}` or `{"structuredContent": <payload>}`): unwrap
  to the helper's input shape before using `negkw-local.js`. Never save truncated output.
- Map result files back to ASINs by content (`adGroupId` / asin column), never by call order.

## 3. SQP shield (targeted, not bulk)
Scale Insights: `get_search_query_data(asin, query:'<token>', query_match:'contains', mode:'raw')`
returns a few rows. Run it before **any** size/dimension phrase negative, and on themes the live
list already blocks heavily. `AsinPurchase > 0` → drop the proposal (and consider a removal).
`CvrIndex` caps at 1.5, so use `ConversionAdvantage` or compute AsinCVR / MarketCVR yourself.

Harvest ordered terms with `get_search_term_performance` (`mode:"raw"`), **not**
`get_search_term_keyword_analysis`: the latter reports noteworthy term→keyword *pairs* only and
returned 9 of 29 ordered terms on a live cross-check against SI's own export.

## 4. Live negatives: one pull per ASIN, local match
Either read the SI textareas (§6; the true target when SI owns the blacklist), or:
`list_resources(resource_type="sp_negative_keywords", integration_id, account_id,
filters={ ad_group_id:"<one broad/phrase ad group>", state_filter:"ENABLED", max_results:500 })`
plus `sb_negative_keywords` for an SB ad group. These are large: let them go to files and parse
locally (`scripts/negkw-local.js dedup`).

Matching rules that matter:
- **Word-sequence containment** for PHRASE (contiguous token run), exact text for EXACT.
- **`ENABLED` only**: ARCHIVED and PAUSED don't block.
- **Filter out zero-length token arrays.** Non-ASCII junk lines normalise to empty and are
  "contained" in everything; one product falsely reported 5 of 6 candidates covered until
  `.filter(p => p.length > 0)` was added. Tell: `LIVE-PHRASE[]`.
- **A live EXACT does not cover a PHRASE candidate.**
- A round **500** means the page is truncated, not that the list is 500 long.
- Ambiguous single candidate → one targeted `keyword_text_filter` check. It is substring-based
  and **profile-wide**: intersect campaign ids with this ASIN's set.

**Over-broad hunt, same data:** intersect the live phrase list with the stopword set
(`the, a, an, and, for, with, of, in, to, on, all`) and the ASIN's own title/fingerprint tokens
(`scripts/negkw-local.js overbroad`). Then the SKC-routing check before flagging:
```sql
SELECT campaignName, SUM(clicks), SUM(purchases7d)
FROM sponsored_products_product_ads
WHERE advertisedAsin='<ASIN>' AND date>='<30d>' AND lower(campaignName) LIKE '%<token>%'
GROUP BY campaignName
```
Campaign exists → routing, leave it. None → real removal candidate.

## 5. Approval sheet (Google Drive connector)
Check the connector's tool schemas first; newer connectors can update, move and share files.
Notes for older, create-only connectors:
- `create_file(textContent=<csv>, contentMimeType="text/csv")` auto-converts to a native Sheet.
  **Do not** send base64 xlsx: about 10 KB of xlsx is about 13,800 base64 characters, corrupts
  silently, and returns the misleading `Invalid conversion requested`.
- **Title at creation is final**: `Negation Audit - <YYYY-MM-DD> (<stage>) - <N> ASINs`.
- Converted sheets land in Drive **root**; the user moves them into their audit folder.
- No permissions tool: the user switches Restricted → Anyone with the link → **Editor**.
- Read back with `read_file_content(fileId)`; if it truncates, `download_file_content` and decode
  locally. **Match on term text, never row order.** A material change after creation → a fresh
  `- v2` sheet.

## 6. Apply: Scale Insights blacklist (the browser route)
Use a browser automation the **user** has signed in to Scale Insights (Playwright with a
persistent profile, or Claude in Chrome). A *rejected* Playwright run-code call can keep executing
in the background and fight you for the tab, so never retry one blind.

- **URL:** `https://portal.scaleinsights.com/Automation/Algo/BlacklistRule/Edit?asin=<ASIN>`
- **Login check = portal ROOT** `https://portal.scaleinsights.com/` → "Dashboard - Scale Insights"
  + account name top-right. `/Identity/Account/Login` renders the password form even when signed
  in, so it always reads "logged out". Never enter credentials.
- **Textareas (DOM order):** `[0]` neg-exact, `[1]` neg-phrase, `[2]` neg-product-target,
  `[3]` exact whitelist, `[4]` phrase whitelist. One entry per line. Blazor Server.
- **Never snapshot** this page (1000+ lines). Evaluate JavaScript only, returning booleans and
  counts.
- **Guard, every call:** `if (textareas.length < 2 || !location.href.includes(ASIN)) throw`. A
  failed save leaves the *next* page mid-navigation, and this guard prevents cross-ASIN writes.
- **Save recipe:**
  1. `Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(ta, cur.concat(adds).join('\n'))`
  2. dispatch `input` + `change` + `blur`, all `{bubbles:true}`
  3. **wait about 3.5 s** for the SignalR round-trip (clicking early saves the stale server model
     and silently drops every addition)
  4. click `input[type=submit][value="Update"]`
  5. success = redirect off `/Edit`; still on `/Edit` = failed → read `.validation-message` /
     `.text-danger` / `[role=alert]`
- Append + wait + click can share ONE call **if the return value is computed before the click**
  (stash it on `window`). Never `await` after the click.
- **Batch reads and verifies only.** Don't chain [nav A, apply A, nav B, apply B] in one batch: it
  mostly works and then silently loses one save.
- **Invalid characters block the WHOLE save** (nothing persists): a `/` slash, and a **spaced
  hyphen** (`august 26 - may 27 desk calendar` blocked 15 terms in one save). A `.` period is
  accepted (`8.5 x 11`). Sanitise or drop the line.
- SI normalises on save (case, whitespace, apostrophes: `father's day` → `fathers day`); accents
  are distinct (`español` ≠ `espanol`: add both). Line counts shift by one or so; not data loss.
- **Competitor ASIN strings → textarea `[2]`** (negative product target), never exact/phrase.
- **Removal is two halves.** Edit the blacklist (and phrase-whitelist the word, SKILL.md §7a),
  then archive the word's ENABLED exact-text phrase copies on Amazon with `update_resources`
  (SKILL.md §7c): SI never archives them. Approved words only; never `delete_resources` or bulk
  files, and never touch a term absent from SI unless it is an approved "ad-group" rescue row.

## 7. Verify
**Navigate for real** and read `textarea.value` after a ~2.5 s settle. A `fetch()` + regex of the
Edit page reads every term as missing: Blazor ships the textareas empty and fills them over
SignalR. Re-apply misses.

## 8. Post-apply artifacts
- **Applied trail**: verified rows only (SKILL.md §9.1). `read_file_content` can truncate
  silently: for a round-trip check, `download_file_content`, decode and diff locally.
- **Product tracker lookups (Monday example):** filter on the ASIN column, not global search
  (Monday's global `search` indexes item NAMES only):
  ```
  get_board_items_page(boardId:<your board>, includeColumns:true,
    columnIds:["name","<asin column>","<sheet link column>"],
    filters:[{columnId:"<asin column>", operator:"contains_text", compareValue:"<ASIN>"}])
  ```
- **Slack:** draft in chat → wait for a yes → send. Applied facts only (SKILL.md §9.3).

## 9. Ads API (MarketplaceAdPros): SB Product Collection Phrase, and the no-SI route

Every run with additions pushes the approved negatives to each ASIN's SB **Product Collection
Phrase** campaigns here, because the SI blacklist does not reach them reliably. Scope with
`list_resources("sb_campaigns", filters={name_filter:"<ASIN or PC naming>"})`, **never** the
report DB, which hides PC campaigns that never served (one product: report said 0, API said 9).
Ad groups resolve in one call (`sb_ad_groups`; `campaign_id` accepts a comma-separated list).
Run the self-block check (`sb_keywords` + `keyword_text_filter`) before writing. Verify with
`campaign_id` **and** `keyword_text_filter` together: a bare per-campaign read caps at 500 and
`total_count: 500` means truncated.

Write shape, for PC-Phrase and for accounts without Scale Insights:
`create_resources({ integration_id, account_id, note, resources:[…] })` with
`{ type:"sp_negative_keywords"|"sb_negative_keywords", campaignId, adGroupId, keywordText,
matchType:"NEGATIVE_EXACT"|"NEGATIVE_PHRASE" }`.
- ⚠️ The match type must carry the `NEGATIVE_` prefix; plain `EXACT` / `PHRASE` is the
  *positive*-keyword vocabulary and is wrong here.
- No `state` field on create. Ad-group level, on broad/phrase/auto ad groups; skip Exact and
  product-targeting ad groups on the SP side.
- Batchable. `PARTIALLY_FAILED` → read the per-index results; `DUPLICATE_VALUE` is benign.
- Limits: **≤ 10 words, ≤ 80 characters, no commas** (`malformedValueError /
  PATTERN_NOT_MATCHED`).
- Read shapes differ from write shapes (reads return lowercase `negativePhrase`), and
  `sb_keywords` reads cap at 100 with no truncation signal.

## Local tooling
`scripts/negkw-local.js` (Node.js): parse saved result files, build the per-ASIN token table,
apply the converter shield, dedup by word-sequence containment, and scan for over-broad live
entries. Run it with `node` and print only the summary:
```
node scripts/negkw-local.js tokens    waste.json converters.json [ASIN]
node scripts/negkw-local.js dedup     candidates.json live.json
node scripts/negkw-local.js overbroad live.json identity.json
```
