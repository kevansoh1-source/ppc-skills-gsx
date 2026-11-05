---
name: amazon-negative-keyword-audit
description: >-
  Weekly negative-keyword ("negation") audit for Amazon Sponsored Products and
  Sponsored Brands, for one ASIN or a pooled batch of many in a single run. Use
  whenever the user mentions negative keywords, negative exact/phrase, a negation
  audit, wasted or bleeding PPC spend, cleaning a search-term report, an
  over-broad negative blocking demand, or the Scale Insights blacklist. Covers
  both ADDING negatives and FLAGGING live ones for removal.
---

# Amazon Negative Keyword Audit

Cut wasted PPC spend on search terms that will never convert, **without** choking off real but
under-tested demand, and without leaving demand-killing negatives live from past runs.

Every rule below came from a real miss on a live seller account. The examples are kept, with the
product details made generic.

## Your setup (read first, fill in once)

The skill works with whatever of these tools you have. On the first run, ask the user for the
values below and suggest they save them in a memory or project note, so later runs don't ask again.

| Setting | What it is | If you don't have it |
|---|---|---|
| Amazon Ads data | **MarketplaceAdPros** connector (report SQL, Ads API reads and writes). Find the integration and the US seller account with `list_amazon_ads_integrations` and `list_amazon_ads_integration_accounts`. Pick the **seller** profile for the marketplace being audited, not an agency or attribution profile. | Required. |
| Blacklist owner | **Scale Insights** (its per-ASIN blacklist page) or **the Ads API directly** (MarketplaceAdPros). | Use the Ads API route (§7, "No Scale Insights"). |
| SQP | Brand Analytics Search Query Performance, through the Scale Insights connector (`get_search_query_data`) or another SQP source. | Skip §5 and treat every size/format negative as PENDING. |
| Approval sheet | Google Drive connector, and the folder where audit sheets go. | Give the approval table as a CSV file instead. |
| Product names | Where the team's own product names live (a Monday board, a spreadsheet), so the sheet shows names the team recognises. | Use the Amazon listing title, shortened. |
| Paper trail | Where the team logs applied negatives per product (for example a PPC management sheet with Negative Exact / Negative Phrase columns). | Skip §9.2. |
| Slack | The channel for the post-apply recap. | Skip §9.3. |
| Click bar | Clicks with 0 orders before a *relevant* term counts as proven waste. Default **17**. Match it to any auto-negate rule the account already runs. | Use 17. |

## The core principle

> **Negate a term only when it is structurally irrelevant to the product, OR it has a real
> click sample and still doesn't convert. Everything else is under-tested, not weak: leave
> it alone.**

A thin week is mostly 1-click terms. A 0-order week on a 1-click term (or on a term you *do*
convert on) is **noise**, not evidence. A negative is permanent and blocks every future
variant, so hold it to a high bar.

## Four rules that override everything (each learned from a real miss)

1. **NEVER apply anything without explicit approval, and approval happens in the SHEET.**
   The team opens the approval sheet and **deletes the rows they don't want; the surviving rows
   are the approved set** (§6). "Run the audit" / "clean this up" / "upload it" is **not**
   approval of the specific terms. Removals need the same sign-off as additions.
2. **Study the ACTUAL product before any format/attribute negative.** Title and metadata are not
   enough for `blank` / `printed` / `write-on` / `fill-in` / `folded` / `flat`. Read the product
   page (main images and A+) or ask the user first. *Real miss:* a thank-you card whose back is
   blank with fill-in lines was nearly negated on `blank`. That card genuinely IS a blank product,
   so `blank` is real demand.
3. **If Scale Insights owns the blacklist, SI alone is still not the complete apply, either way.**
   - **Additions:** editing the SI blacklist is step one. SI propagates to Amazon on its own
     schedule and does **not** reliably reach Sponsored Brands **Product Collection Phrase**
     campaigns, so §7b pushes the same approved negatives there through the Ads API on every run.
   - **Removals:** taking a word off the SI blacklist leaves every Amazon copy ENABLED. A word
     removed from SI was still enabled on Amazon two months later. So an **approved** removal has
     two halves: remove it on SI and phrase-whitelist it (§7, §7a), then archive its ENABLED
     phrase copies in every SP and SB ad group of that product (§7c).
   - **What still holds:**
     - Archive only words in the approved set, and only exact-text phrase copies.
     - Never "reconcile" SI against the Ads API for additions.
     - Never build a bulk-operations file.
     - Never touch anything nobody approved. Hundreds of unrequested archive operations once came
       from ignoring this.
     - An ad-group-level negative that is not on SI may be archived only when it is an approved
       row of the table (rescue rows marked "ad-group"). Any other term absent from SI: surface it
       and stop.
4. **Measure the already-live LEAK before proposing anything new.** Terms already ENABLED on an
   ASIN's blacklist can keep taking spend, and on a real account this leak was consistently
   **bigger than the net-new work** the same run proposed. Report it (which ASINs, how much, is
   the blacklist rule enabled) and let the user decide. Do not try to fix it through the Ads API.
   Leakage scaled with list SIZE, which hints at a cap or truncation on what SI pushes: worth
   testing.

## Source hierarchy: what to trust

**SQP > STR > third-party (DataDive, Helium 10 and the like).**
- **SQP** (Brand Analytics Search Query Performance) counts **all** purchases on a query
  (organic and ad). It is the *second* converter shield and catches what STR structurally
  cannot (§5). In Scale Insights, `CvrIndex` caps at 1.5: use `ConversionAdvantage` or divide
  AsinCVR by MarketCVR yourself.
- **STR** (PPC search-term report) is what you paid for and whether it converted,
  **ad-attributed only**. Two uses: the waste list (spend > 0, 0 orders) and the converter shield
  (orders >= 1). In Scale Insights, harvest with `get_search_term_performance`;
  `get_search_term_keyword_analysis` is an opportunity engine, not a ledger (it returned 9 of 29
  ordered terms on a live cross-check).
- **Third-party** data is a pre-launch guess. Never a reason to negate.

**Dedup against the LIVE lists, never a team spreadsheet.** Spreadsheets lag; the live SI
blacklist textareas (or `sp_negative_keywords` / `sb_negative_keywords`) are the truth.

## Cost discipline: pool the SQL, don't loop the skill

The default is **many ASINs in one run with one combined approval sheet** (30 ASINs in one run
works). That is affordable *because the SQL is pooled*, not because coverage is cut.

- **Pool with a DISTINCT semi-join, never a raw join.** Joining `search_terms` to `product_ads`
  fans out by the number of product ads per ad group and inflated clicks and spend 30 to 100
  times on a real run (one term read 931 clicks against a true 11).
  `JOIN (SELECT DISTINCT advertisedAsin, campaignId ...)` is a semi-join and does not inflate.
- **⚠️ Then EXCLUDE every multi-ASIN campaign: the semi-join does not save you from this.**
  A DISTINCT semi-join fixes click *inflation* but not *cross-attribution*: a campaign advertising
  N ASINs hands its entire search-term list to all N, so each one looks like it is taking the
  others' traffic. Run the pre-check as a **filter, not a warning**:
  ```sql
  SELECT campaignId FROM sponsored_products_product_ads
  WHERE advertisedAsin IN (<batch>) AND date >= '<30d>'
  GROUP BY campaignId HAVING COUNT(DISTINCT advertisedAsin) > 1
  ```
  then add `AND campaignId NOT IN (<those ids>)` to the scope subquery. One 30-ASIN batch had
  11 such campaigns (one spanning 25 ASINs, a cross-selling product-targeting campaign spanning
  17), and without the exclusion the ASINs contaminated each other. Say in the sheet that their
  genuine cross-sell waste is therefore out of scope.
- **Disbelieve any cross-category result; verify it un-joined before proposing anything.** A
  planner once appeared to be taking hundreds of dollars of greeting-card traffic. The raw
  campaigns showed **zero** card-term clicks: a bad-scope artifact, not waste. The tell is a token
  set that has nothing to do with the product. One `GROUP BY campaignName` with a
  `SUM(CASE WHEN searchTerm LIKE '%<token>%' ...)` settles it.
- **7d and 30d in ONE pass** via `SUM(CASE WHEN date >= <7d> THEN ... END)`.
- **`run_report_sql` hard-caps at 1000 rows**: chunk the ASIN list (about 6,500 waste rows needed
  9 chunks of 30 ASINs).
- **Never read big payloads into context.** On hosts that save oversized results to a file,
  parse that file locally and print only the answer. Hosts without that must save each response
  to a run folder themselves (references/connectors.md, section 2).
- **No subagent fan-out** unless the user asks. Parallel agents each re-read the same payload.
- **Cached fingerprints** (§0): derive once per ASIN, never weekly.
- **Cheapness comes from pooled pulls, not from judging fewer terms.** A version that sampled
  top-N-by-spend missed obvious relevance failures sitting in the 1-click tail. Scan everything.

## Prerequisites (tools)

MCP tool prefixes differ between installs: **find tools by function name** (ToolSearch in Claude
Code), never hardcode a prefix.

- **Report DB (MarketplaceAdPros):** `run_report_sql` over `sponsored_products_product_ads`,
  `sponsored_products_search_terms`, `sponsored_brands_search_terms`.
- **Scale Insights (optional):** `get_search_term_performance` (per-term ledger, SP+SB),
  `get_search_query_data` (SQP shield), `get_product_metadata`.
- **Live negatives:** the SI blacklist page (read in a browser the user is signed in to), or
  `list_resources` (`sp_negative_keywords`, `sb_negative_keywords`) for the Amazon-side view.
- **Apply, SI route (§7):** a browser automation the user has signed in to Scale Insights
  (Playwright with a persistent profile, or Claude in Chrome).
- **Apply, Ads API (§7b and the no-SI route):** `list_resources`, `create_resources`.
- **Approved removals, Amazon half (§7c):** `list_resources` + `update_resources`
  (state `ARCHIVED`).
- **Delivery (optional):** Google Drive (`create_file`, `copy_file`, `read_file_content`,
  `trash_file`), the team's product tracker, Slack (**ask before every post, §9**).

`references/connectors.md` has the exact SQL, schemas and gotchas.
`scripts/negkw-local.js` does the local dedup, token table and over-broad work (needs Node.js).

## Workflow

### 0. Load the cached fingerprints and the team's product names
Read `data/fingerprints.json` for each ASIN (create it from `data/fingerprints.example.json` on
the first run). Fingerprint = contents · size · format (printed/blank/write-on, folded/flat,
stickers) · audience · occasions · with/without envelopes · pack count. Derive only when an ASIN
is **missing** (`get_product_metadata`, SP-API product details, or a product-page read), then
write it back. Every negate/keep call is judged against this.

⚠️ **Format attributes MUST be confirmed against the product page** whenever a format-based
negate is on the table (rule 2). The title lies by omission.

⚠️ **In the same step, resolve every ASIN to the team's own product name** (from the product
tracker in "Your setup"). The sheet's `PRODUCT` column must carry the name the team uses, never
the Amazon title and never the fingerprint description, which the team won't recognise. Do the
lookup **now**, not as a formatting step at the end, so the name is also ready for the applied
trail and the recap. With a Monday board, one `execute_code` call that paginates
`items_page(limit:500)` + `next_items_page` and matches the ASIN column covers a whole batch.

### 1. Resolve scope: SP **and** SB, pooled
- **SP:** distinct `(advertisedAsin, campaignId)` from `sponsored_products_product_ads` for the
  whole ASIN list. Trust `advertisedAsin`, **not** the campaign name: some SP campaigns carry
  no ASIN or a wrong one.
- **SB:** if your SB campaign names carry the ASIN, map with
  `regexp_extract(campaignName, 'B0[0-9A-Z]{8}')`. Otherwise map SB campaigns to ASINs from the
  Ads API (the campaign's creative or product list).
- Every campaign acted on must map to an ASIN in the batch. Never let a scope step substitute a
  different ASIN.

### 2. Pull the FULL waste list and both shields
- **Waste** = spend > 0 AND orders = 0, **7d and 30d in one pass**, across **both**
  `sponsored_products_search_terms` and `sponsored_brands_search_terms`. The orders column is
  `purchases14d` on SP and `purchases` on SB. Keep **all** rows including 1-click: a term can
  live on SB only, and the low-spend tail is where most relevance failures live.
- **Shield A, STR converters** (orders >= 1, 30d), per ASIN. **Build it from SP *and* SB pooled
  into one set before judging anything.** An SP-only shield is a trap: `stickers` once looked like
  a clean, product-page-confirmed format failure on a glow-tattoo product (the page says "not
  stickers") with no SP converter, but it converted on SB (`glow in the dark stickers for
  halloween`). It was the biggest proposal in the run and would have killed live demand. Cheapest
  way to get this right: pull waste and converters in the SAME query (drop the `HAVING ... = 0`,
  return `orders_30d`, and split into waste and converters locally).
- **Shield B, SQP** (§5), targeted rather than bulk.
- **Re-run the shield as a mechanical gate right before the sheet is built, not just during
  judgement.** Check every proposed term against every converting term for that ASIN by
  word-sequence containment and drop on any hit. That pass caught 6 of 194 proposals on one run,
  including two of the three largest, after they had survived a careful manual read. List the
  drops in the sheet so the team can see what was protected.

### 3. Relevance-gate at scale (the judgment)
Don't read thousands of raw terms. **Per ASIN, build a token → (terms, clicks, spend) table, then
subtract every token that appears in that ASIN's converters**: a mechanical converter shield
(`node scripts/negkw-local.js tokens`). A few thousand unshielded tokens across 30 ASINs is
readable and keeps full coverage.

A **relevance failure negates on ANY clicks** (1 click is enough, and this is most of the value).
A merely *relevant* non-converter needs the **click bar** (default >= 17). Theme sweep: list the
OFF categories from the fingerprint and scan for each:
- **Wrong product** (`crafts`, `books`, `small bible` when you sell bookmarks)
- **Wrong theme / off-niche** (`patriotic`, `halloween` on a faith product)
- **Wrong denomination / sub-segment** (`catholic` on a non-denominational product)
- **Wrong occasion / audience** (`daughter`, `get well`, `teens` on an adult/general product)
- **Wrong size / format**: ⚠️ the least reliable category; always SQP-check it (§5)
- **Too generic** (bare `gifts` / `books` pulling off-product traffic → phrase)
- **Wrong specificity** (`psalms 23` when the set is assorted)
- **Competitor brand**, or wholesale bulk of a different item

**Classify EXACT vs PHRASE: default off-theme / off-attribute TOKENS to PHRASE.** One
`underwater` phrase beats five `thank you cards underwater` exacts and stops future variants
leaking. Keep EXACT for genuinely one-off queries. **Singular ≠ plural** in phrase match
(`scratchers` does not block `scratcher`): negate both if both leak.
Limits: **≤ 10 words and ≤ 80 characters**; **no commas** (Amazon returns `PATTERN_NOT_MATCHED`;
don't auto-strip, because stripping usually collapses into an existing term).

### 4. Dedup against the LIVE list, and hunt over-broad entries in the same pass
Read each ASIN's live negatives **once** (SI textareas in the browser, or `list_resources`
`max_results:500` → file → parse locally with `negkw-local.js dedup`). Match **locally**, never
with per-candidate API calls:
- **Word-sequence containment**: an existing PHRASE blocks a candidate when its token sequence
  appears contiguously in the candidate. Filter to `ENABLED` first.
- **⚠️ Drop zero-length entries before matching.** One junk line (non-ASCII entries normalise to
  zero tokens) makes *every* candidate read "already live". Tell: a whole ASIN comes back covered
  with an empty bracket, `LIVE-PHRASE[]`.
- **Match-type aware**: a live EXACT does **not** cover a PHRASE candidate (exact `lunch` blocks
  only "lunch", not "gold lunch napkins").
- A round 500 result means the list is truncated, not complete.

**Same pull, second job: find over-broad live negatives** (these outrank the additions: they
suppress more demand than a week of additions recovers). Intersect the live phrase list against
(a) a stopword set (`the, a, an, and, for, with, of, in, to, on, all`) and (b) the ASIN's own
title/fingerprint tokens (`bulk, set, pack, blank, laminated, watercolor, inspirational, planner`,
the product noun). Real finds: `the` live on a product and blocking a converter; `and` blocking a
product's biggest search term; `construction` on a product whose top converter was
"construction thank you cards".

**Before flagging any of them, check for single-keyword-campaign (SKC) routing:**
```sql
SELECT campaignName, SUM(clicks), SUM(purchases7d)
FROM sponsored_products_product_ads
WHERE advertisedAsin='<ASIN>' AND date>='<30d>' AND lower(campaignName) LIKE '%<token>%'
GROUP BY campaignName
```
**Dedicated campaign exists → LEAVE IT** (the negative is deliberate traffic routing; removing it
starves that campaign). **No campaign → real removal candidate.** Same evidence, opposite answers:
`construction` had no campaign (removed), `birthday` had four birthday SKCs (left alone).
Also confirm the negative actually *could* block the converter: phrase match is word-based, so
`composition` never blocks `comp`.

Removals go to the user as a **FLAGS** section; removing is their call.

### 5. SQP shield: mandatory before any size/dimension phrase negative
Before proposing a phrase negative on a **size token**, or on a theme the live list already blocks
heavily, run `get_search_query_data(asin, query:'<token>', query_match:'contains', mode:'raw')`.
If `AsinPurchase > 0`, **drop the proposal** and consider whether an existing live negative should
be removed instead. This killed 5 of 120 proposals the STR shield had cleared on one run, all
wrong-size phrases that looked like textbook relevance failures: `5x7` converting on a 4x6
product at 50% CVR against a 7.5% market, `4x6` on a 5x7 product, `3x5` on two 4x6 products.
Shoppers search a size as a rough proxy, not a filter.

### 6. GATE: deliver the approval sheet and WAIT
Build ONE workbook for the whole run. Tabs: **APPROVAL** (decision rows, plain-English REASON),
**FLAGS** (over-broad removal candidates), **PENDING-format** (blocked on a product-page check),
**Competitor ASINs**, **README**. When it ships as one CSV (one tab), those become labelled
section blocks in the order below.

**⚠️ ORDER IS FIXED: the proposed negatives go at the VERY TOP.** Row 1 = the column header,
row 2 = a single "how to approve" line, then straight into the APPROVAL rows. Close them with an
`END OF APPROVAL BLOCK - <N> proposed negatives` marker and put **everything else underneath**:
run summary, the already-live leak, FLAGS, SQP-shield drops, PENDING-format, zero-net-new, method
notes. This holds **even when a background finding is the bigger number**. Do not open the sheet
with a headline callout.

Column order: `SECTION, ASIN, PRODUCT, TERM, MATCH, CATEGORY, REASON`. `PRODUCT` is the team's
product name from §0.

**Google Drive connector notes.** Check the connected tool schemas first: newer connectors can
update, move and share files; older ones could only create. With an older connector:
- **Title it right at creation; it cannot be renamed.** Format:
  `Negation Audit - <YYYY-MM-DD> (<stage>) - <N> ASINs`.
- **Contents cannot be edited in place** (`update_file` was metadata-only). Any correction means
  `create_file` a fresh `- v2` sheet and `trash_file` the old one, so nobody approves from a
  stale copy. Say in chat that you trashed it (Drive trash is recoverable).
- **Native Google Sheet** via `create_file` with **CSV `textContent`**, not base64 xlsx (large
  base64 silently corrupts and returns the misleading `Invalid conversion requested`). Sheets land
  in Drive **root**; tell the user to drag it into their audit folder. If the connector cannot set
  sharing, the user switches Restricted → Anyone with the link → **Editor** themselves.

Post the link, the counts and the date-window caveat in chat. **Then stop.**

**Approval = the rows they leave behind.** Read the sheet back fresh after they edit
(`read_file_content`, and `download_file_content` if it truncates), **match on term text, never
row order**, and apply exactly the surviving APPROVAL rows. If they edited a term in place (for
example shortened a full EXACT query to a PHRASE token), honour the edit but flag material scope
changes before writing.

### 7. Apply, Scale Insights route: the SI blacklist in the browser
Per-ASIN URL: `https://portal.scaleinsights.com/Automation/Algo/BlacklistRule/Edit?asin=<ASIN>`.
SI fans out to all campaigns itself: no SP/SB scope resolution, no per-ad-group writes.

**The browser.** Use a browser the **user** has signed in to Scale Insights: Playwright with a
persistent profile, or Claude in Chrome. Never type credentials; ask the user to sign in.
- **Drive the user's existing browser; don't pop up a new window** over their work. With
  Playwright over CDP, connect to the running browser and **reuse an open `scaleinsights.com`
  tab**, opening a new tab (not a new window) only if none exists:
  ```js
  const b = await chromium.connectOverCDP('http://127.0.0.1:<port>');
  const ctx = b.contexts()[0];
  let page = ctx.pages().find(p => /scaleinsights\.com/.test(p.url()));
  const reused = !!page; if (!page) page = await ctx.newPage();
  // ... work ...
  if (!reused) await page.close().catch(() => {});
  await b.close();
  ```
  If the automation browser isn't running, say so and ask the user to open it, rather than
  launching one yourself.
- Per ASIN: go to Edit → `waitForFunction(() => document.querySelectorAll('textarea').length >= 2)`
  (Blazor hydrates late: a plain read right after navigation sees **0** textareas) → guard on
  ASIN-in-URL → native value setter on `textarea[1]` + input/change/blur → wait 3.5 s → click
  Update **once** → poll up to **60 s** for the URL to leave `/Edit` (long lists take 25 to 45 s)
  → re-navigate and read back.
- Tools that report a *different* tab on consecutive calls cannot be trusted for
  verify-then-write. Use them for read-only probes at most.

⚠️ **Re-dedup at the SI textarea before writing, always.** The Amazon-side
`sp_negative_keywords` view under-reports badly: once it called all 74 approved terms net-new
when SI already held 34. Do a read-only dry pass over every ASIN first, then write only what is
genuinely missing.

- **Login check: open the portal ROOT** `https://portal.scaleinsights.com/`. A signed-in session
  shows "Dashboard - Scale Insights" with the account name top-right. **Do NOT check
  `/Identity/Account/Login`**: it renders the password form even for a signed-in session, so it
  always reads "logged out".
- **Textareas in DOM order:** `[0]` neg-exact, `[1]` neg-phrase, `[2]` neg-product-target,
  `[3]` exact whitelist, `[4]` phrase whitelist. One entry per line. Blazor Server.
- **Guard every write:** `if (textareas < 2 || !urlContainsThisAsin) throw`. This is what stops
  one ASIN's negatives landing on another when a navigation is mid-flight.
- **Save recipe:** native `HTMLTextAreaElement.prototype` value setter → dispatch
  `input` + `change` + `blur` (bubbling) → **wait about 3.5 s for the SignalR round-trip** →
  click `input[type=submit][value="Update"]`. Clicking early saves the stale server model and
  silently drops every addition. Compute the return value **before** the click and stash it on
  `window`; don't `await` after the click (navigation kills the evaluation).
- **Success = redirect off `/Edit`.** Still on `/Edit` = FAILED; read `.validation-message` /
  `.text-danger` / `[role=alert]`.
- **⚠️ Do NOT chain apply-then-next-navigate in one batch call.** It mostly works and then
  silently loses a save. Batch the **reads and verifies** freely; give each **apply** its own call.
- **Invalid characters block the ENTIRE save** (one bad line, nothing persists): `/` slash and a
  **spaced hyphen** are rejected; `.` periods are fine. Sanitise or drop the line. Accents are
  distinct (live `español` does not block `espanol`; add both). SI normalises case, whitespace and
  apostrophes on save (`father's day` → `fathers day`), so line counts shift.
- **Competitor ASIN strings (`b0xxxxxxxx`) are negative PRODUCT targets**: textarea `[2]`, never
  exact/phrase. Surface them separately and ask.

**No Scale Insights?** Apply the approved rows through the Ads API instead
(references/connectors.md, section 9): `create_resources` with `sp_negative_keywords` /
`sb_negative_keywords` at ad-group level on the product's broad, phrase and auto ad groups, then
verify each write with a filtered read. §7b still applies to SB Product Collection campaigns.

### 7a. Removals on SI: also phrase-whitelist the word
When a removal is approved:
- take the exact line out of textarea `[1]`;
- add the converters it unblocks to `[3]`;
- add the word itself to `[4]`, the phrase whitelist. This is meant to stop an SI
  "remove 0-conversion words" rule from adding it back. That effect is unverified, so check the
  next nightly run.

### 7b. Apply ALSO to the SB Product Collection Phrase campaigns (every run with additions)
**The SI blacklist does NOT reach Product Collection campaigns reliably.** After §7 succeeds,
push the **same approved negatives** to each ASIN's SB **Product Collection Phrase** campaigns
through the Ads API.

- **Scope from the API, NEVER from the report DB.** `sponsored_brands_search_terms` contains
  only campaigns that actually *served*, so it hides PC campaigns with no impressions. On one run
  the report showed **0** PC-Phrase campaigns for a product while the API showed **9**: scoping
  from the report would have written 2 negatives instead of 18.
  ```
  list_resources(resource_type="sb_campaigns", integration_id, account_id,
    filters={ name_filter: "<ASIN or your PC naming>", max_results: 100 })
  ```
  Keep every campaign whose name marks it as Product Collection **and** Phrase (naming variants
  exist, such as `Product Collection Ad - Phrase - 1` or `... - Highest - Phrase - 4`).
- **Include PAUSED campaigns.** A negative on a paused campaign is harmless and protects it when
  it is re-enabled. Report the enabled/paused split.
- **Ad groups: one per SB campaign**, fetched with
  `list_resources("sb_ad_groups", filters={campaign_id:"<comma,separated,ids>"})`: this filter IS
  multi-valued, so all campaigns resolve in one call. An ad group reading `PAUSED` may just be
  dayparting, **not** a reason to skip it.
- **⚠️ Self-block check BEFORE writing, scoped to the target campaigns with both filters.**
  A PC negative list has previously blocked the campaign's own targeting keywords. Use
  `list_resources("sb_keywords", filters={campaign_id:"<this ASIN's PC-Phrase ids>",
  keyword_text_filter:"<term>", max_results:50})`. `total_count: 0` = safe; any row means that
  term would block the campaign's own keyword, so drop it for that campaign and say so.
  **Do NOT use a bare profile-wide `keyword_text_filter`**: a common term returns 100+ rows
  account-wide, caps at 100 with a `next_token`, and is inconclusive without paginating.
- **Write:** `create_resources` with
  `{type:"sb_negative_keywords", campaignId, adGroupId, keywordText, matchType:"NEGATIVE_PHRASE"}`.
  Batch freely; include a `note` naming the approval sheet.
- **⚠️ Verify with `campaign_id` + `keyword_text_filter` TOGETHER.** A bare per-campaign read
  caps at 500 rows and `total_count: 500` means *truncated*, so a fresh term may not appear on
  page 1 and looks like a failed write. The two-filter query returns `total_count: 1` and is
  definitive. Match the returned `keywordId` against the one `create_resources` returned.
- **An ASIN with no PC campaign is a normal outcome, not a failure.** Say so and note those terms
  are live on the blacklist from §7.

### 7c. Removals on Amazon: archive the enabled copies (MarketplaceAdPros)
Scale Insights never archives these, so do it after the SI save.

1. **Scope: the product's ENABLED campaigns, SP and SB.**
   - `list_resources` `sp_campaigns` / `sb_campaigns` with `{state_filter: "ENABLED",
     name_filter: "<ASIN>"}` (if your campaign names carry the ASIN; otherwise scope from
     `sponsored_products_product_ads`). SB returns 100 per page, so follow `next_token`.
   - Don't page the whole account's campaigns.
   - A campaign that advertises several products (SQL `advertisedAsin` per ad group) is archived
     only for words approved for every product in that ad group.
2. **Read the negatives per campaign.**
   - `list_resources` `sp_negative_keywords` / `sb_negative_keywords` with `{campaign_id,
     state_filter: "ENABLED", max_results: 1000 (SP) / 500 (SB), next_token}`.
   - ⚠️ `keyword_text_filter` is a **substring** match ("marks" returns every "bookmarks …";
     "for" returns "forvencer"). Account-wide word queries are therefore useless.
   - At scale (hundreds of campaigns), save each result to a file and run a local script that
     keeps only exact-text matches.
   - SB rows come back lowercase: `matchType: "negativePhrase"`, `state: "enabled"`.
3. **Select** rows whose whole text, lowercased and trimmed, equals an approved word, with phrase
   match and enabled state. Never select:
   - multi-word phrases that merely contain the word ("whats for dinner");
   - exact negatives;
   - words that stay on the blacklist.
4. **Archive** with `update_resources`, at most 500 per batch, one batch at a time:
   - SP item: `{type: "sp_negative_keywords", keywordId, state: "ARCHIVED", level: "ad_group"}`;
   - SB item: `{type: "sb_negative_keywords", keywordId, adGroupId, campaignId, state: "ARCHIVED"}`.
   - Give each batch a `note` naming the rescue, the date, the ASIN, the approval and "batch n/N".
   - Log every change-set id; `undo_change_set` reverses a batch.
5. **Verify on a sample.** Re-read a few SP and SB ad groups with `{ad_group_id, state_filter:
   "ENABLED", keyword_text_filter: "<word>"}` (expect no exact phrase match left), and one with
   `state_filter: "ARCHIVED"` (expect the archived row).

Scale: a single word can have thousands of copies across a product's ad groups (one rescue
archived over 11,000 copies in 25 batches, about 75 minutes, 0 failures). Lessons:
- **De-duplicate on keyword id across every collection pass.** A second pass re-collected 838
  rows already queued.
- **The SB update item must carry `adGroupId`.** Without it, every row fails.
- **Expect exact negatives equal to converters in the sample reads.** They are out of scope for a
  phrase-word rescue. List them for the next audit's SKC-routing check (§4) instead.

### 8. Verify, by real navigation only
**You cannot verify by `fetch()`-ing the SI Edit pages and regexing `<textarea>`.** Blazor ships
the textareas EMPTY and fills them over SignalR, so everything reads as missing even when the save
succeeded. **Navigate to each Edit page and read `textarea.value` after a ~2.5 s settle.**
Re-apply any misses.

### 9. Post-apply deliverables (in this order)
Deliver 1 and 2 without asking: they are the expected output of every run. Only #3 (Slack) has a
gate, and that gate is absolute.

⚠️ **Every deliverable reports BOTH writes: the blacklist (§7) AND SB Product Collection Phrase
(§7b).** The PC-Phrase write is easy to drop from the write-up because the blacklist is where the
terms are "decided". Before showing any recap, trail or chat summary, check it names: total
PC-Phrase negatives created, total PC-Phrase campaigns (enabled + paused), the per-ASIN campaign
count, and every ASIN that had **no** PC-Phrase campaign (blacklist only). If §7b wrote nothing,
say that explicitly too.

1. **Applied trail** (Drive, or a CSV file). Title:
   `Negation Audit - <YYYY-MM-DD> (APPLIED) - <N> negatives, <M> ASINs`.
   Include only rows that actually saved AND passed the independent read-back: per ASIN, term,
   match type, medium, live-phrase count before/after.
   Sections: `SI APPLIED (net-new)` → **`SB PC-PHRASE`** (one row per approved term: created on
   *k* PC-Phrase campaigns (enabled + paused) and verified by read-back, with change-set ids; or
   "no PC-Phrase campaign for this ASIN, blacklist only") → `SI REMOVED` → `AMAZON ARCHIVED`
   (§7c: copies archived per word, change-set ids).
   With an older Drive connector, a `parentId` on `create_file` can break the CSV-to-Sheet
   conversion. Workaround: create in root with no `parentId`, `copy_file` into the target folder
   with the same title, `read_file_content` the copy to confirm, then `trash_file` the original.
2. **Paper trail for the team's log**, one block per ASIN that had terms applied. **Emit TWO
   SEPARATE fenced code blocks per ASIN**, so each gets its own copy button. The heading and the
   link to that product's log sit OUTSIDE the fences. Per ASIN:

   **`<ASIN>` — `<team product name>`**
   `<link to the product's log or PPC sheet, if the team has one>`

   then a fenced block:
   ```
   NEGATIVE EXACT
   <terms, one per line, or literally "(none)">
   ```
   then a second fenced block:
   ```
   NEGATIVE PHRASE
   <terms, one per line, or literally "(none)">
   ```
   Don't wrap everything in one fence (one copy button for a blob the team must split by hand,
   and the link stops being clickable). Both headers appear on every ASIN even when one side is
   empty. Hand the blocks over; don't auto-write a grid the team edits by hand.
3. **Slack recap**: draft it, **show it in chat, and ASK before every single post**, then post
   to the team's channel. The recap carries the applied trail link from #1.
   ⚠️ **ASK EVERY TIME, NO EXCEPTIONS.** "Post this to Slack" / "send it" is a request to
   *prepare* the post, **not** permission to skip the review. Show the exact text and wait for a
   distinct yes. A follow-up post needs its own approval.
   Format:
   ```
   Negative-Keyword Audit — <YYYY-MM-DD> (<N> ASINs) — APPLIED ✅

   Added: <N> net-new (<X> exact + <Y> phrase)
   Applied to: <blacklist> + SB Product Collection Phrase campaigns (<P> negatives across <C> PC-Phrase campaigns, enabled + paused)

   <ASIN> — <product name>
     - Exact: term, term
     - Phrase: term, term
     - PC-Phrase: <k> campaign(s)        ← or: none (no PC-Phrase campaign) — blacklist only

   Also removed from <ASIN> (blacklist + <n> Amazon copies archived): <terms>

   No new negatives — already fully maintained (0 net-new):
     - <ASIN> — <product name>   (one line why: already live / under-tested / converting)

   Review sheet: <approval sheet link>
   Applied trail: <applied trail link>
   ```
   **The recap covers WHAT WAS APPLIED, nothing else.** Cut every analysis paragraph before
   showing the draft: no rejected candidates, no product-page findings, no propagation
   discussion, no bid or profit escalation, no connector caveats. **The `Applied to:` line and the
   per-ASIN `PC-Phrase:` lines are part of what was applied and are never cut.** Keep the one-line
   scan summary (terms and spend scanned, candidates → already live → proposed → applied).
   Reasoning belongs in the sheet; economics go to the user in chat. Add "(revised)" and a
   one-line correction to the header if it replaces an earlier post.

## The decision rule

**✅ NEGATE only if:**
- **Product-relevance FAILURE** (any click count): wrong product, wrong theme/niche, wrong
  denomination, wrong audience/occasion, wrong format, competitor brand, wrong language/market,
  or wrong **size** *after* the SQP check clears it.
- **Proven waste**: a *relevant* term at or over the **click bar** with 0 orders. If the account
  already runs an auto-negate rule at that bar, this path is mostly handled already, and an
  over-the-bar 0-order term you "discover" is usually a fan-out artifact: verify it un-joined
  before believing it.

**🚫 NEVER negate:**
- Anything **SQP shows you convert on** (organic counts, so a 0-order STR week is noise).
- **Under-tested** relevant demand (under about 10 to 17 clicks, no clear relevance failure).
- A **product component** the pack includes and that converts.
- **Impressions but about 0 clicks**: no spend, no waste signal.

## Guardrails

- **Approval happens in the sheet; surviving rows are the approved set.** Removals need sign-off
  too. Then verify what actually saved.
- **ASK before EVERY Slack post, including follow-ups.** "Post it" means draft it and wait.
- **APPROVAL rows go at the very top of the sheet**, everything else below the
  `END OF APPROVAL BLOCK` marker.
- **`PRODUCT` = the team's own product name**, never the listing title or the fingerprint text.
- **Product page before any format negative.** `blank` / `write-on` / `fill-in` / `printed` are
  real demand on a fill-in product.
- **SQP-check every size/dimension token.** It is the least reliable relevance category.
- **With Scale Insights, the apply is TWO writes: the SI blacklist (§7) AND the SB Product
  Collection Phrase campaigns (§7b).** Scope PC from the API, never the report DB; run the
  self-block check first; verify with `campaign_id` + `keyword_text_filter` together.
- **Report the PC-Phrase write in every deliverable** (trail, recap, chat summary).
- **Removals need both halves.** Remove the word on SI and phrase-whitelist it (§7a), then
  archive its enabled Amazon phrase copies (§7c). Never archive anything outside the approved
  rows, and never reconcile additions against the Ads API.
- **Report the already-live leak every run, before the new proposals.**
- **Check SKC routing before calling a live negative over-broad.**
- **Default off-theme tokens to PHRASE**; singular ≠ plural; ≤ 10 words / ≤ 80 characters; no
  commas.
- **Never raw-JOIN search_terms to product_ads**: DISTINCT semi-join only. Sanity-check every
  click count.
- **EXCLUDE multi-ASIN campaigns from per-ASIN attribution.** The semi-join stops inflation, not
  cross-attribution.
- **Build the converter shield from SP + SB pooled**, and re-run it as a mechanical containment
  check over the finished proposal list before the sheet ships.
- **Never take a full accessibility snapshot of the SI blacklist page**: it dumps 1000+ lines.
  Evaluate JavaScript and return counts only.
- **Never read oversized tool results into context**: parse the saved file with Node.
- **Separate transport/UI failures from permission denials.** Retry transport or UI failures only
  after checking whether the write landed. A permission or sandbox denial stops that action:
  report the exact action, its scope and the denial reason to the user. Never route around a
  denial with another tool, browser or permission setting.
- **Never claim a write landed because the tool said so.** Report only what an independent
  read-back confirms, and name what is still outstanding.
- **Write currency as `USD 12.34`, never a dollar sign directly followed by a digit**: slash-command
  argument substitution expands those tokens and corrupts the amount when the skill loads.
- **Never commit or paste credentials, and never type a password.** The user signs in to every
  web app themselves.
- **Scan the FULL waste list.** Relevance failures negate on any clicks and the 1-click tail is
  where most of them live.
- **When unsure, keep it.**
