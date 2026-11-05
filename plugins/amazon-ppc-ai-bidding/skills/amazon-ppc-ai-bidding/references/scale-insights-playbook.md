# Scale Insights web app (Chrome)

The Scale Insights MCP reads data and can apply bid change sets, but **cannot** change which strategies or rules
are attached to ad groups, edit the blacklist/whitelist or create import rules. Those are done in the web app at
portal.scaleinsights.com, through Claude in Chrome, with the user's OK. The account is logged in by the user;
never handle the password.

## Reading grids without rendering them

The pages are Kendo grids with server paging. Read data directly; rendering 1,000 rows froze the tab once:

```js
const g = jQuery('#<gridId>').data('kendoGrid');
const r = await new Promise((res, rej) => g.dataSource.transport.read({
  data: { page: 1, pageSize: 2000, sort: [], group: [],
          filter: { logic: 'or', filters: [{ field: 'AssociatedASIN', operator: 'eq', value: 'B0…' }] } },
  success: res, error: rej }));
// r.Data = rows, r.Total = count
```

**Output rules.**
- Return small summaries, not rows.
- Strip HTML and replace `= & ? ;` before returning. Output that looks like query strings or cookies is blocked by
  the browser tool.
- `dataSource.view()` is an ObservableArray: wrap it in `Array.from`.

## Pages

| Page | URL | Grids / fields |
|---|---|---|
| Keyword targeting (assign objective) | `/Automation/Strategy/Keyword` | Assignment grid `#Automation_Objective_KeywordTargeting_AssignObjective_GridTable` (StrategyName, AssociatedASIN, CampaignName, AdGroupName); strategies `#KeywordStrategyTable` (RuleId, Name, AssignedToAdGroups, *RuleDisplayHtml). Same pattern on `/Automation/Strategy/Auto`, `/Product`, `/Video`, `/VideoProduct`, `/Display` |
| Strategy editor | `/Automation/Strategy/Keyword/Edit?id=N` | Sections `#bid #import #negative #negativeWord #revive #status #dayParting`; blacklist checkbox `#RuleDB_NegativeBlacklistRule`; description `#RuleDB_Description` (≤250 chars) |
| Assigned rules | `/Automation/AssignedRules` | 5 grids (keyword, auto, product, brand, display): AssociatedASIN, AutomationStrategyId/Name, BidFilter, ImportFilter, NegativeFilter, BlacklistFilter, DayPartingFilter |
| Blacklist/whitelist (assignment) | `/Automation/Algo/BlacklistRule` | SP grid `#Automation_Algorithm_Blacklist_Products_AssignRule_GridTable` (RuleFilterString = "Blacklist enabled"), SB grid; "Unassign rules" button |
| Blacklist/whitelist (lists) | `/Automation/Algo/BlacklistRule/Edit?asin=<ASIN>` | Textareas `#NegativeExactList #NegativePhraseList #NegativeProductTargetList #ExactWhiteList #PhraseWhiteList`; submit "Update" |
| Import rules | `/Automation/Algo/ImportRule` | SP assignment grid `#Automation_Algorithm_Import_Products_AssignRule_GridTable`; rules list (RuleName, CriteriaDisplay, PercentOfAverageCPC, MinBid, NewMatchType); import history (CreatedShortDate, ASIN, Keyword, MatchType, RuleName, Change) |
| Create import rule | `/Automation/Algo/ImportRule/Create` | `#Rule_Name`, `#Rule_Description`, source dropdown (0 = SP), criteria picker (rc-select; hidden `Rule.CriteriaProfileId`), `Rule.NewMatchType`, `Rule.ImportOnlyUniqueKeywordMatch`, SQP conditions, `Rule.PercentOfAverageCPC` / `MinBid` / `MaxBid`, "Create" |
| Automate assignment | `/Automation/Strategy/AutomateAssignment` | Per-ASIN "Automatically Assign Objectives" preview. **Don't use on AI-managed products:** it re-evaluates every ad group by strategy criteria |

## Recipes

### Clone a strategy (never edit a shared one)

1. On the editor, click "Clone strategy". In the dialog, set the name input that starts with "[Clone]" using the
   native value setter plus input/change/blur events.
2. Click "Save as new strategy". This opens the Create page.
3. Remove rule chips: `#<section> .k-chip-remove-action` (dispatch a click).
4. Untick `#RuleDB_NegativeBlacklistRule` with `.click()`.
5. Add an import rule: section "+", search in the modal, tick it, OK.
6. Click "Create strategy". The new id shows in `#KeywordStrategyTable` (RuleId).

### Assign a strategy to many ad groups

1. Filter the assignment grid: `g.dataSource.query({page: 1, pageSize: 200, filter})`, e.g. ASIN + CampaignName
   contains "Exact SKC".
2. Tick the header checkbox: `thead input[type=checkbox]`, via `.click()`.
3. Set `jQuery('#StrategyId').data('kendoDropDownList').value('<id>')`, then `.trigger('change')`.
4. Click "Assign".
5. Verify with a fresh `transport.read` grouped by StrategyName.

### Remove the blacklist from ad groups

- **Why.** Strategy changes don't remove a per-ad-group blacklist assignment.
- **How.** On `/Automation/Algo/BlacklistRule` (SP tab), filter the same ad groups, tick them, click "Unassign
  rules". That removes only the blacklist rule; the strategy and dayparting stay (verified 2026-10-17 on one ad
  group first, then 98).
- **Verify:** RuleFilterString is empty for those rows, and Assigned rules shows BlacklistFilter empty.
- **Exact owners never carry it (Kim, 2026-10-29, decision 170).** No ad group on 103 (exact SKCs) or 144 (brand video
  exact owners) may show "Blacklist enabled". At onboarding, and whenever a new SKC or SB exact owner is assigned its
  strategy, read the product's rows on `/Automation/AssignedRules` (KeywordTargetingTable and VideoAdsTable,
  `transport.read` filtered by AssociatedASIN): every row with AutomationStrategyId 302497 or 302500 must have an empty
  BlacklistFilter. Unassign any that don't, as above, on the Sponsored Products or Sponsored Brands tab.
- **Sponsored Brands rows:** the Assigned rules video grid leaves AdGroupId at 0. Find the same ad groups on the
  Blacklist page's Sponsored Brands grid by CampaignName (`eq`), which carries the real AdGroupId.
- **Batches:** 200 ad groups a query, tick the header, check the ticked count equals the rows, click Unassign, wait
  about 8 seconds, re-read. 1,082 went through this way on Oct 29 with no dialog.

### Edit the whitelist or blacklist lists

1. On `Edit?asin=<ASIN>`, append lines to the textarea with the native setter plus input/change/blur.
2. **Wait about 3 seconds** for Blazor to sync, then click Update (`input[type=submit][value=Update]`).
3. Success = redirect to `/Automation/Algo/BlacklistRule`. Re-open and re-read to verify.

Notes:
- One invalid line (e.g. a "/") blocks the whole save. The page then stays on Edit and says "[Exact Whitelist] Invalid
  characters in …". Write the search with the character replaced by a space ("w/ pockets" → "w pockets"):
  `blacklist_rescue.whitelist_text` does this.
- `español` and `espanol` are different entries.

### Blacklist rescue (Kim, 2026-10-21)

No Invest or Prove-first search may sit on its product's blacklist: not as itself, not as a close variant (plural,
"book marks", "markers") and not inside a phrase entry ("turkey" blocks "turkey stickers"). The 2026-10-21 sweep found
34 such entries on 11 of 24 products. Run it at onboarding, and whenever a run adds an invest search.

1. **Read the lists into `<run>/si_blacklist.json`,** from any Scale Insights page (same origin):
   ```js
   const html = await fetch('/Automation/Algo/BlacklistRule/Edit?asin=<ASIN>', {credentials: 'include'}).then(r => r.text());
   const doc = new DOMParser().parseFromString(html, 'text/html');
   const L = id => (doc.querySelector('#' + id)?.value || '').split(/\r?\n/).filter(s => s.trim());
   // {NegativeExactList, NegativePhraseList, ExactWhiteList, PhraseWhiteList}: return counts first, then the lists
   ```
   Add `"_read": "<SGT time>, Scale Insights blacklist page"`. Long lists (1,000+ entries) come back in parts.
2. **Plan:** `plan.py` reads the file and, when an entry blocks an invested search, adds a "Scale Insights setup" row
   (step 95, a person's call) listing `exact_remove`, `phrase_remove` and `whitelist_add`; `summary.blacklist_rescue`
   says whether it was checked. On its own: `python scripts/blacklist_rescue.py --asin <ASIN> --lists <run>/si_blacklist.json
   --run <run>` writes `blacklist_rescue.json` with the new list contents.
3. **Apply** on the Edit page, after the approval: remove exactly those lines, add the whitelist lines, Update (recipe
   above), then re-read the page and re-run the check: no entry may block an invested search.
- **Never rescued:** `config.json` `scale_insights.blacklist_keep` (the brand "yourbrand": organic only, Kim
  2026-10-20), nor any search that holds it ("yourbrand birthday cards"): rulebook 2f, since 2026-10-26.
- **A one-word phrase entry** ("mini", "journal", "turkey") comes off the whole product's blacklist, so that word is
  allowed again in every ad group the blacklist reaches. That is the price of keeping the invested search visible; the
  funnel negatives still route the search to its owner.
- Removing an entry does not archive negatives Scale Insights already pushed into Amazon ad groups. The live check (b)
  (`close_variants.py`) still runs on every invest SKC's ad group.

### Rename or edit a strategy (learned 2026-10-17)

1. Open `/Automation/Strategy/<Keyword|Auto|Product|Display|Video|VideoProduct>/Edit?id=N`.
2. Set `#RuleDB_Name` (**80 characters at most**, or the save silently fails with "Please enter Strategy objective
   name") and `#RuleDB_Description` (250 at most). Both are Kendo widgets: `jQuery(el).data('kendoTextBox')` /
   `'kendoTextArea'`, then `.value(v)` and `.trigger('change')`.
3. Click `#btnSave`. A dialog asks "update the existing strategy / save as a new strategy": keep the radio
   `#UpdateGroup` at "0" (update existing) and click `#btnUpdate`. Success = redirect to the strategy list.

### Add a rule to a strategy

- In the editor, each section (`#bid`, `#import`, `#negative`, `#dayParting`, …) has a "+" button that opens a
  modal (`#BidModal`, `#DayPartingModal`, …) listing every rule with a checkbox or radio.
- Tick the row by script (find the input whose row text starts with the rule name, `.click()` it), check the footer
  says "1 rule selected", then click the modal's OK by script. Mouse clicks here are often caught by the sidebar.
- Then save the strategy as above. Verify the chip appears (`#BidSelected`, `#DayPartingSelected`) and, after
  saving, the strategy grid's `BidRuleDisplayHtml` / `DayPartingRuleDisplayHtml`.

### Create a bid rule

- `/Automation/Algo/BidRule/Create`. Criteria come from a picker with "+ Create new criteria" (an Ant Design modal:
  metric, "At least ≥" / "At most ≤", value; open its selects with a `mousedown` on `.ant-select-selector`, then
  click the `.ant-select-item-option`).
- **Read criteria carefully:** the picker shows "0 Orders" for "at most 0", but "≥ 0 Orders" means *any* number of
  orders. Some old team profiles named "… 0 Orders" are "≥ 0 Orders" (e.g. 800255 "> 20 Clicks & 0 Orders").
- The action radios (Target ACOS, Fixed amount, Percentage, State change) stay disabled until the form validates:
  trigger `input` on `#PPCRuleBidDB_Name` after setting it, then click "Percentage".
- Fields: `DaysToAnalyse`, `DaysToIgnore`, `DaysToPauseChange` (observe changes made by automation),
  `DaysToObserveManualChange`, `BidPercentAdjustment_Decrease` + `BidPercentAdjustmentDecrease`, `PPCRuleBidDB_MinBid`.
  Success = redirect to `/Automation/Algo/BidRule/Index?newRuleId=N`; re-read the rule in
  `#Automation_Algorithm_Bidding_Rules_GridTable` (ComputationType 2, PercentAdjustment −30, …).

### Remove a per-ad-group dayparting schedule

**New AI onboarding default (Kim, 2026-10-24):** use 203 / 21246 on every AI-controlled SP, SB and SD
group, including low-bid/audience and new harvest/rank groups. Select verified exclusive IDs, replace legacy
direct assignments with 21246, and independently read back `RuleIdList` and the strategy schedule. An empty
direct list is sufficient only with verified strategy inheritance of 21246. Preserve shared exclusions and
explicitly approved schedule exceptions. Never edit the legacy rule itself; other products may still use it.
Do not declare onboarding complete from strategy labels or a zero-unassigned count alone.
**No AI product stays on Scale Insights rules (Kim, 2026-11-04, decision 180).** Every product moved to AI bidding
comes off its legacy strategies and rules onto the AI objectives (101/102, 103 and 144 for exact owners with the
blacklist unassigned, 104/105, 111, 121, 131, 141 to 143; ids in config.json `scale_insights`) with 203 / 21246.
Its legacy direct schedules ("Minimal 5-6am", product schedules) give way to 21246 after its AI bids are written and
read back, before the ~02:10 SGT nightly run (decision 135). Shared campaigns and `ownership_scope` shared groups keep
their setup.

- On `/Automation/Algo/DayPartingRule`, the SP and SB grids (`…DayParting_Products_AssignRule_GridTable`,
  `…DayParting_Brands_AssignRule_GridTable`) show each ad group's `RuleFilterString`, e.g. "Minimal - Only 5-6am on
  Mon-Sun, Optimum Hours".
- Collect the ad group IDs with a `transport.read` filtered by ASIN, then `g.dataSource.query` with an `or` filter on
  `AdGroupId`, tick the header checkbox, check the ticked count, and click that tab's "Unassign rules".
- It removes the per-ad-group schedules; the strategy's own schedule stays (verified 2026-10-17 on one ad group,
  then 94). Give the strategy Optimum Hours first if it has none (302494 had none).

### Which dayparting rule an ad group really runs

- In the dayparting grids, `RuleFilterString` lists the ad group's own rules **and** its strategy's, sorted
  alphabetically: "Almost all the time (5am to 11pm), Optimum Hours" does not say which one is the ad group's own.
- `RuleIdList` holds only the ad group's own rule ids. Its own rule wins; the strategy's applies only when
  `RuleIdList` is empty. Count schedules by `RuleIdList`, and map ids to names from `#DayPartingRuleTable`.
- Found 2026-10-17: four Sponsored Brands video low-bid groups labelled "Almost all the time…, Optimum Hours" were
  running Optimum Hours (their own rule); "Almost…" came from the team strategy "Low Bids - Videos - ASINs w Sales -
  Max $0.27".

### Sponsored Brands video exact owners (strategy 144, to create once)

- The AI's Sponsored Brands video keywords own their invest searches, like the exact SKCs in Sponsored Products. They
  must not get the blacklist or the negative rules: Amazon applies close variants to negatives and would switch them
  off.
- **One-time setup (done 2026-10-22: 144 = 302500, `config.json` → `sb_video.si_strategy`):** on the Brand video
  keywords page, clone 141 into "144 Brand video exact owners - never blocked, optimum hours": no bid, negative or
  import rules, blacklist unticked, dayparting 203.
- **Each new SB video campaign:** once Scale Insights syncs it, assign 144 to its ad group, and check the blacklist
  isn't assigned.

### New campaigns

- **Sync timing.** Campaigns created through MAP appear in Scale Insights after its next ad-group sync, often
  about an hour. "Refresh ads" queues a sync but may not include brand-new campaigns.
- **Until synced** they have no strategy, and so no dayparting. When they appear, assign them; don't leave them
  unassigned.
- **Empty ad groups never appear.** An ad group with no keyword or target is missing from every assignment grid:
  the strategy pages, Assigned rules and the Import rule page. This held even though the campaign itself had
  synced (checked 2026-10-17 on the two harvest campaigns). Give a new ad group at least one keyword before you
  try to assign it.
- **The dayparting grid sees new ad groups first.** After the harvest placeholder keywords went in (2026-10-17
  about 14:05 UTC), the ad groups showed on the Dayparting rule page within minutes, but not on the Keyword
  targeting page, which waits for the keyword sync.

## Gotchas

- **Click hijacked.** The left sidebar expands on hover and steals clicks: hover far right first, or click by
  `ref`/JS.
- **Frozen tab.** Screenshots can time out on heavy pages: retry at a lower scale, or read text/DOM instead.
- **Nightly run.** Bid/negative rules run around 18:10–18:30 UTC. Finish rule changes before then.
- **Auto-assignment criteria.** Strategy auto-assignment criteria (priority, match type, campaign/ad group name
  contains) only apply through Automate assignment. Setting them is harmless; running that tool on our products
  is not.
