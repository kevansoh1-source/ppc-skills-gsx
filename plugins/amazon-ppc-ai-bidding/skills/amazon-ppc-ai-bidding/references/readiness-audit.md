# Onboarding-readiness audit (read-only)

Documented 2026-10-24 SGT from the two saved audits and `runs/codex-briefs/onboarding-audit-2026-10-23.md`.
**Optional since 2026-10-30 (decision 172).** Use it only when a person explicitly asks for a read-only, test or shadow
check of a product not yet AI-owned. "Audit <ASIN> for the AI bidding skill" on such a product means onboard it and run it
(onboarding.md), not this. Answer whether it is ready and what its first plan would do. One ASIN per run. This mode never
onboards a product, even if the verdict is ready or the planner labels rows Auto. **Not for an AI-owned product with Auto on:** its audit or re-audit is an operational run (weekly-run.md)
that applies its eligible Auto rows (decision 116, 2026-10-24).

## 1. Boundaries and preflight

These limits override this skill's operational instructions, including automatic application and publication:

| Allowed, only when the operation reads existing data | Banned in this mode |
|---|---|
| SI `get_*` (including account resolution as needed); MAP `get_*`, `list_*`, `describe_*`, `search_*` and `run_report_sql` SELECTs; contextual bid recommendations; SP-API price/catalog/inventory reads | MAP `create_resources`, `update_resources`, `delete_resources`, `update_listing*`, `create_listing*`; SI `propose_*`, `apply_change_set`, `undo_change_set`; every other connector mutation |
| DataDive `list_*` / `get_*` for existing radar/niche data and quota | DataDive `create_*`, `add_*`, `pause_*`, `resume_*`, `delete_*`; no quota-consuming job or radar creation, even within quota |
| Monday board/item reads and other explicitly required pure reads | Any Monday, Slack, Gmail, Drive/Sheets or Railway write; all browser actions |
| Local analysis and shadow planning within this audit's run folder | Dashboard mutations (`publish`, `claim`, `release`, `applied`, `lineup`, `refresh`, etc.); `notify.py`, `autonomy.py`, `routine.py`, `log_invest.py`; git writes and any file write outside the run |

A tool name is not permission: verify its semantics. A search that launches a job is not a read. Never type a
password or expose credentials. If a required connector is missing or signed out, stop and identify it. A permission
denial stops that action; preserve the exact reason and hand it back, without changing tools or permissions.
The delegated approvals-`never` behavior is in repository `docs/agent-setup.md` section 8.

Read `AGENTS.md`, this skill's `SKILL.md`, `onboarding.md`, `data-pull.md`, `live-checks.md`, and repository
`docs/open-items.md`, the latest `docs/decisions.md`, `docs/knowledge/si-mixed-asin-ownership-2026-10-23.md` and
`docs/knowledge/si-blacklist-self-blocking-skcs.md`. Check the ASIN in `docs/sweep-tiers.md`, the local product
registry if present, and the negative audit's `data/fingerprints.json`. Read current dashboard ownership/claims
only if available through a permitted read; never claim the product for an audit. Report unknown ownership.
Start from a current checkout: `git pull` as at any session start (AGENTS.md), so product files, scopes and
decisions are current. A Codex task delegated into the coordinator's checkout does not pull: the coordinator
already did; say in the report which commit the audit read.
An AI-owned product with Auto on does not use this mode (decision 116): run its operational audit instead. Use this
mode for one only when a person explicitly asks for a read-only or shadow check, and label it that way. If an
operational run's preflight fails, report the run as blocked; do not fall back to this mode.

## 2. Isolate the draft and evidence

Create repository `runs/<ASIN>-<YYYY-MM-DD>-audit/`, with the date in SGT. Write **only** there. The draft is:

`runs/<ASIN>-<date>-audit/data/asins/<ASIN>.json`

Set `"auto": {"enabled": false}` and `"registry": {"stage": "audit"}` in the draft, retaining other necessary
registry fields. Never put it in the skill's `data/asins/`: the routine treats product files there as live AI
products, with Auto on by default. Do not edit live product files, `config.json`, docs, logs or decision records.

Use `onboarding.md` section 1 for the schema, not its live actions. Set identity, SKU, campaign prefix from an
actual campaign, current price, SI UnitProfit and `economics_as_of`, verified size, and fingerprint-derived
relevance. Preserve documented size-specific protections. Do not inherit another product's IDs, invest clocks,
approvals or ownership exception from a template. Read the Monday launch record; if missing, record that, or label
an alternative board's evidence explicitly. Do not substitute the catalog date. Inventory, lifecycle notes and
the book owner matter: sell-through/discontinued status is a decision to reconcile, not permission to invest.

Pull the files in `data-pull.md` through reads only. Save each complete response explicitly, in a supported JSON
shape, before summarizing; validate the response ASIN/account and window, all pages and truncation. Keep raw
sources separate from normalized inputs. Also gather 30-day and 12-month sales/spend/profit, inventory, current
listing/price and fee assumptions. For annual totals, use non-overlapping returned windows and disclose gaps and
partial months. Distinguish the requested period from the actual returned coverage. A stale fingerprint price
does not override current economics. Keep fee discrepancies visible rather than silently choosing a favorable fee.

## 3. Establish ownership across SP, SB and SD

Create `ownership_inventory.csv` (or equivalent JSON) with ad product, campaign/ad-group/ad IDs and names,
separate states, all advertised ASINs, exclusive/shared/unknown status, SI strategy/rule evidence or unknown,
source file and read time. Include zero-spend and paused objects; paused does not mean unshared.

1. Start with all-state campaign-name searches, then verify actual membership. For SP, inspect product ads in
   **every group of each candidate campaign**, not only ads filtered to this ASIN. Supplement with actual-ASIN
   report SQL to find serving cross-name campaigns. A report cannot discover every idle cross-name campaign.
2. For SB, inspect ads/creatives, including Product Collections' full ASIN lists, and their campaign/group IDs.
   Names and blank SI Associated ASIN fields cannot prove exclusivity. Inspect known shared campaigns and sibling
   creatives as well as name matches. One mixed creative makes its **whole campaign and all descendants** shared,
   including any single-ASIN ads elsewhere in that campaign.
3. Read SD product ads and their campaign/group membership, even though this planner never writes SD bids.
   Product-wide SI setup, rules or lists can affect SD and other advertised ASINs. In the 2026-10-24 card audit,
   SD reads found four campaigns each advertising 15 ASINs, including an existing AI product. Skipping SD would
   have missed that ownership conflict. Use all-account membership pagination when available; disclose any narrower
   coverage. Read all ads in each discovered candidate campaign to establish its full membership.
4. Compare exact shared campaign IDs and member ASINs against local AI product `ownership_scope` records,
   including the products in decisions 109 and 111. Record overlaps and missing exclusions; edit no live records.
   Those decisions are named exceptions, not authority to invent a new exception for the audited product.
5. Read SI campaign settings and available automation coverage for the identified IDs. Report separately what
   these tools actually expose. They do **not** establish per-group strategies, direct bid rules, dayparting,
   import assignments or blacklist/whitelist contents merely because a settings call succeeded. A missing ID or
   a high-spend-only coverage sample is not proof of no rules. Sam unknown fields and list the later signed-in
   portal checks. No browser is used in this audit.

Explain how campaigns were found and what remains unsearched. Name matching plus recent reports is partial
coverage, not an account-wide ownership certificate. Shared campaigns and shared product-list behavior stay
SI-owned pending Kim's scope decision. Record proposed exclusions as recommendations, never as approved scope.

## 4. Check serving blockers and product fit

Inspect existing exact SKCs before interpreting absent performance rows as missing owners or inadequate bids.
Read keyword and parent states, ad eligibility, and ad-group negatives, matching own terms and close variants.
Use MAP `sp_negative_keywords` with `ad_group_id` and `keyword_text_filter` for stem checks; use all negatives
without a text filter when needed for full-group coverage. Save IDs, states, match types and evidence.

On 2026-10-24, `sp_campaign_negative_keywords` filtered by `campaign_id` returned `level: ad_group` rows.
Check actual levels and IDs; do not use that read to clear either level. See `data-pull.md`, "Negative-resource
level check". No self-blocking negative found in selected groups does not clear campaign negatives or SI lists.
SI's blacklist can recreate a removed Amazon negative, and whitelist presence does not stop that propagation.
Describe the rescue and required approval/source-list verification; never archive, whitelist or negate here.

Check current product dimensions against every proposed promotion, invest, harvest seed and blacklist rescue.
The product-size gate (rulebook section 2) uses product `size`, then fingerprint `size`; 6x4 and 4x6 match,
including spaced forms, inch units and decimals. Orders and generic protections such as "thank you" do not
justify a 5x7 promotion for a 4x6 product. An existing documented protection explicitly naming a size is an allowed
size decision; do not add one to make a plan pass. Unknown size remains unknown and needs verification.
The current gate holds wrong-size raises, new campaigns, budgets and pauses; a bid cut retains its normal lane.
No audit row is applied. Relevance negatives still require the negative audit's approval.

Record missing eligibility windows, schedules, recommendations and placement evidence. Seven calendar days are
not seven verified eligible days. An enabled campaign with a paused group is not a serving replacement; later
replacement-dependent pauses require moderation clearance, enabled parents and actual serving evidence.

## 5. Run the isolated shadow plan

From `.claude/skills/amazon-ppc-ai-bidding/`, using absolute paths and the audit's SGT date:

```text
python scripts/plan.py --asin <ASIN> --run "<absolute audit folder>" --mode onboard --data "<absolute audit folder>/data" --today <YYYY-MM-DD>
```

The `--data` argument is mandatory: inspect it and the draft's Auto-off/stage fields before running. Capture stdout,
stderr and the exit code under the run folder. On success, generate only the local preview:

```text
python scripts/preview.py --out "<absolute audit folder>/preview.html" "<absolute audit folder>/plan.json"
```

Do not open a browser or publish it. Review `plan.json`, lane counts, payload folders and ownership boundaries.
An Auto classification is hypothetical; the isolated Auto-off draft routes eligible rows for review. Nothing in
any generated folder authorizes application. Check for shared-campaign rows, unsafe broad SI instructions,
wrong-size promotions, unsupported intent, harvest gate discrepancies and decisions absent from For-human counts.

**If the planner refuses, stop planning and report the refusal.** Preserve its message, exit code and missing-input
files. Do not bypass stale SQP/launch/input guards, add fallback markers, change dates, switch Auto on, invent bids,
edit the planner or rerun to force a result. Missing suggestions for queries never requested are missing inputs,
not proof Amazon has no suggestions. The later onboarding can gather them under its own workflow. Without a
completed plan, lane counts, final promotions and preview are unavailable, not zero; raw candidate terms are not
final roles. The B0SAMP0011 audit on 2026-10-24 is an example of this valid audit outcome.

## 6. Save the report and handoff

Write `<run>/audit.md` and give the same substantive report to the requester:

1. **Verdict:** ready / ready with fixes / not ready for the planned week, with the reason, ASIN, book owner,
   marketplace, audit time in SGT and planned week if known. Readiness today is not a future launch snapshot.
2. **Dated figures and windows:** current price, profit per unit and breakeven ACOS; 30-day and 12-month ad spend,
   total/ad sales, ACOS, TACOS, organic share, reported profit and stock cover. Label units versus revenue share,
   attribution lag, incomplete periods and estimates. State SQP stage and query evidence: mature window coverage
   does not mean every query is trusted or the 50/50 organic-unit goal is met.
3. **Blockers/fixes, highest priority first:** exact IDs/evidence, next action and who decides. Book owner for
   ordinary setup/bid work and rescues, Lee for product/listing direction, Kim for program entry, shared
   ownership, price and nonstandard rules/dayparting. State unknowns explicitly, including connector limitations.
4. **First-plan review:** completed/refused status, lanes and payload locations; proposed Invest/Prove-first
   searches, bids/budgets, biggest cuts/pauses, harvest, SB video, For-human items and independent reviewer concerns.
   No completed plan means these are unavailable; never turn candidate data into invented planner output.
5. **Remaining onboarding work:** refreshed economics/membership/serving evidence, verified exclusive harvest
   campaign and qualifying size-checked seed, SI rules/import/blacklist/whitelist setup and exact-ID readback,
   existing/new rank tracking after quota check, MAP apply verification and Day-1 check. Describe; do not execute.
6. **Coverage and connector-call ledger:** `connector_calls.txt` lists every invocation's tool name, including
   repeats and failed calls, in order. Optionally use `connector_calls.json` for sequence, safe scope/window,
   outcome and saved-response path, without credentials. Include distinct names and call count in the report so
   the coordinator can verify reads only. State no browser, live writes, dashboard/Slack, git mutations or live
   product edits occurred. Name any missing evidence rather than claiming complete clearance.

A ready verdict goes to a person; it does not activate Auto. Kim must approve joining, and any shared campaign
needs his recorded `ownership_scope` before a write (decisions 109 and 111). The later authorized run follows
`onboarding.md` from section 1, refreshes live evidence and regenerates the plan under current scope. It never
applies the audit's saved payload directly. Keep the audit as dated evidence, not the live product state.
