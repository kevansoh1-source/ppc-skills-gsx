# Team dashboard

**Current UI, Oct 19, 16:24 SGT:** the changes-first overview, shared bid/rank role legends and human-only decision inbox are published. Needs Human has only genuine human decisions, not AI-work/scheduled/history tabs. Each ASIN ends with For human decision; retained operational records are folded under Context & audit → Follow-ups & history. No task was marked complete by this presentation change. The earlier layout descriptions below are historical where they conflict; current contract and build/publication instructions are in `docs/dashboard-ui.md`. This page still cannot accept replies or trigger a worker.

**Placement recommendations (local build, 2026-10-18):** each product page now has a Placements
section showing current/proposed TOS, product-page and rest-of-search modifiers, campaign-level
CVR/CPC/economics, data windows and explicit hold reasons. Filters separate sufficiently sampled
rows, proposed changes and all holds. See [placements.md](placements.md). Deployment/publication
and any later Ads changes require their own preview approval; this section never writes ads.

**Publication update (2026-10-18, 17:17 SGT):** Kim approved deployment. Placement-aware
proposals for five additional ASINs and nine Needs human reviews are live and verified.
Numerical placement policy and Amazon changes remain unapproved; publication is not application.

One page per AI-managed product, plus one per product lined up for AI bidding. The team sees what is live, what
is waiting for approval, what comes up next and what not to touch, without opening Scale Insights or the ads
console. Built 2026-10-17 for the bookmarks pilot (B0SAMP0001, B0SAMP0002); eight more products lined up the
same day.

- **URL:** https://your-dashboard.example.com. Each product page has its own link,
  `/#/<ASIN>`.
- **Viewing is public** to anyone with the link (Kim, 2026-10-17): the Railway variable `DASHBOARD_PUBLIC` is
  `true`. The page is `noindex`. Remove the variable (or set it to anything else) to bring back the team-password
  sign-in: any user name plus `DASHBOARD_PASSWORD` from the run owner's `~/.config/your-ppc-repo-dashboard/secrets.env`.
- **Publishing always needs the publish token,** in every mode. **Approving or declining a bid row needs your personal
  token** (the shared token can't): see "The Bids card" below.
- **Hosting:**
  - Railway project `your-ppc-repo-dashboard`; its IDs are in `config.json` → `dashboard`.
  - One Bun function, `dashboard/server.ts`, with a 500 MB volume at `/data`.
  - Railway holds only SHA-256 hashes of the password and the publish token.

## The menu

- **Needs human** (`#/needs-human`): decisions only (decision 97, 2026-10-22). Publishing sends only `human_ready`
  items, without the research write-up (`human_review.for_people`); research and monitoring items stay in the product
  file. Older text below about research items on this page describes the pages before that change. Research
  stages separate pending AI work, human-ready recommendations and monitor/query-fit explanations.
  The human-ready count excludes legacy flags without completed market research. It is a cross-product listing and price work queue, with type/status/search
  filters, priority, owner, dated conversion evidence, source/window and outcomes. Price suggestions show
  current/proposed amounts and before-ad contribution margins only when backed by economics and a rollback.
  No live listing or price writes. Workflow and item contract: [needs-human.md](needs-human.md).
  Each weekly run also adds one **Bids** item per ASIN here, with an Approve and Decline button on every row (see "The Bids
  card" below).

- **For Growth** (`#/for-growth`, added 2026-10-22, not live yet): the Growth team's listing passes, one card per product
  with a paste-ready block and two status buttons. Not a Needs-human item. Publishing sends it whole
  (`human_review.for_people` passes it through like the Bids item). See "For Growth: the tab, the status route and
  the Growth keys" below and [for-growth.md](for-growth.md).

- **First row:** "All products" and one tab per product type (`config.json` → `product_types`, in that order),
  each with its product count. Keep type labels to one or two words ("Notebooks"; the longer wording goes in the
  type's `note`).
  The All products count includes every published ASIN, including onboarding products. The index refreshes on
  route navigation. Crafts includes blank puzzles; register new type IDs in config before publishing or they
  fall back to Other. Verified 15 published products on 2026-10-19 SGT.
- **Second row:** appears only once a type is chosen (its page, or one of its products' pages) and lists that
  type's products by their short name (`product`). The current product is filled in.
- **Type pages:** `/#/c/<type id>`, e.g. `/#/c/bookmarks`: the goal board, who's working, coming up, the product
  cards and the activity, for that type only.
- On phones the header scrolls away with the page, and both rows scroll sideways.

## The home page

0. **Needs a decision** (only when there is one): every open item with status `decision`, across the products in
   view, with the product's name first. The card carries them as `decisions` (dashboard.py `decisions_of`).
1. **Goal: 50% organic, 50% from ads.** A strip of counts (on goal; at 50/50 but losing money; ads carry most
   sales; more organic than 50/50; lost money after ads), then one row per product, grouped by type: name, month
   N of 12, the 50/50 bar, organic and ad shares with the change on the 30 days before, the status and profit
   after ads. "How to read this" folds away the explanation.
2. **Who's working on what** (claims).
3. **Coming up:** dated items across products.
4. **Products by type:** one card per product: thumbnail, name, Amazon title, ASIN and SKU, AI-managed or
   lined-up status, decisions needed, the brief's headline, then launch, last 30 days, who's working, just changed,
   what is optimised and what's next. AI-managed products first in each group, then lined-up ones in queue order.
   The 50/50 bar is on the goal board only. A line that is the same on every card in view (owner, headline, what
   is optimised) is said once in the lede ("10 products, all AI-managed since Oct 17") and left off the cards.
5. **Recent activity,** one fold per day: the latest day open, older days folded, with "Open all" / "Fold all".
6. **How this works** and the hands-off rules.

## What a product page shows

In order:
1. **Header:** "← <type>" back link, thumbnail, name, Amazon title, launch date and "month N of 12", then the
   **goal box** (status, the 50/50 bar, profit after ads, ACOS against breakeven, the 30-day window), then the
   status pills (bid owner, what is live, next weekly run, who is working on it) and "Copy link".
2. **On this page:** one button per section below; it scrolls there (the URL's # is the router, so no anchors).
   On screens wider than 560px it sticks under the header and marks the section being read. Each button also writes
   the section into the link (see "Links" below), so "Copy link" shares where you are.
3. **What's happening** and the next steps (the product file's `brief`).
4. **Open items and dates:** decisions first, then open items by due date, then done.
5. **Just changed:** the latest run counted by change type, who published and approved it, and the three latest
   activity lines.
6. **Tiles:** price and profit, breakeven click, invest searches and budgets, planned investment, harvest, next
   review. Then **Last 30 days** (the product file's `monitor`).
7. **Invest searches** (AI-managed products): live settings, the baseline at the start, review dates, any "fix
   due next run", and the investment estimate.
8. **What is being optimised:** a one-line count by owner; the full optimisation map unfolds on click.
9. **Changes in the latest run**, by type, with skipped or changed rows marked.
10. **Harvest:** status, starting bid, gate and IDs.
11. **Search terms by verdict.**
12. **History**, one fold per day, newest first: the product file's dated activity lines (by time) and the
   team's dashboard events that day. Then every published version.
13. **Rules and references:** hands-off rules, the rulebook, the IDs and the sources.

Every table downloads as CSV. Column notes (a header's hover text) are also written under the table, for touch.
On phones the change and invest tables keep the first column, the role and the main value ("$0.40 to $0.80"); the
row button opens the other columns and the row's campaign, ad group and keyword IDs.

### Links

| Link | Opens |
|---|---|
| `#/` | Home |
| `#/c/<type>` | One product type |
| `#/<ASIN>` | A product page |
| `#/<ASIN>/v/<version>` | An earlier version |
| `#/<ASIN>/<section>` | A product page at one section: `brief`, `items`, `just`, `monitor`, `rank`, `invest`, `scope`, `changes`, `harvest`, `terms`, `history`, `about` (the `JUMP` keys) |
| `#/<ASIN>/changes?type=Bid+change&role=Invest&q=bookmark` | Latest run, unfolded, with that change type, bid role and filter |
| `#/<ASIN>/terms?verdict=leave&q=cross` | Search terms with that verdict and filter |

The address bar follows the jump buttons and the filters (without adding history entries). Unknown sections and
values fall back to the page's defaults.

### Readability rules the page follows (audit 2026-10-17)

Checked against the Vercel Web Interface Guidelines, ui-ux-pro-max, impeccable, Anthropic's frontend-design skill and
Nielsen Norman Group's tab and menu research:
- body text 16px, secondary text never under 14px, lines under about 75 characters;
- numbers in tabular figures; long tables shaded on alternate rows;
- chart marks at 3:1 against the background (organic in the darker brand teal; a darker edge on the gold);
- status is never shown by colour alone (every bar has a text label);
- the current tab and product are marked two ways (underline or fill, plus colour); the two menu rows look
  different (tabs, then chips);
- tap targets at least 44px on phones; visible keyboard focus; no sideways page scroll at 375px;
- light and dark themes, with the browser's theme colour set.

## Product identity and the 50/50 goal (every product file)

Added 2026-10-17 at Kim's request: products must be easy to recognise, and the page must show how far each one
is from the goal.

| Field | What | Where it comes from |
|---|---|---|
| `name` | What the product is, in plain words, with what tells it apart: "Christian bookmarks (cross design)". | Written by hand. `product` stays the short label for the menu ("Cross"). |
| `type` | The home-page group: an id from `config.json` → `product_types`. | Written by hand; add a type to `config.json` if none fits. |
| `amazon_title` | The listing title as it is on Amazon. | Scale Insights `get_product_metadata` → Title. |
| `image` | The main image, `https://m.media-amazon.com/images/I/<id>._SL160_.jpg`. | Scale Insights `get_product_metadata` → Thumbnail, with `_SL75_` changed to `_SL160_`. The page shows only images from m.media-amazon.com. |
| `launch_date`, `launch_source` | The team's launch date, and which board it came from. | Monday board 2 (Launch) or 3 (Focus), "Date Launched". Never the catalogue date. |
| `monitor.prior` | The 30 days before the monitor window: `start`, `end`, `sales`, `ad_sales`, `ad_spend`, `profit`, `organic_share` (null without sales). | Scale Insights `get_sales_data` for the previous 30 days. |

**The goal** (`config.json` → `goal`: `organic_share` 0.5, `stretch_organic_share` 0.6, `horizon_months` 12). Since
2026-10-22 (Kim, decision 99: "my goal is to get about 50% organic to 50% ppc units ordered.. or at least about 60%
organic to 40% ppc") a product is **on goal** at 50% organic units or more and profitable after ads; 60% organic, 40%
from ads is the stretch target; within 12 months of launch. Until then the goal read "orders about half organic and half
from ads, at about breakeven" (decisions 1 and 4). The page computes, from the monitor block:
- **organic share** = sales without an ad click, all ad types (Scale Insights); ad orders ≈ orders × ad share;
- **status** (Kim, 2026-10-22: "On goal is 50%+ organic"): "On goal" (50% organic or more and profitable after ads),
  "On goal, 60%+ organic" (the stretch target reached), "50%+ organic, but losing money", or "Ads carry most sales"
  (under 50% organic; "…after 12 months" once past the horizon). The goal board counts on goal, on goal at 60%+, 50%+
  but losing money, ads carrying most sales, and lost money after ads. Until 2026-10-22 the page drew "On goal" as
  within 10 points of 50% (`band` 0.1, now removed);
- **trend:** the change in organic share on the 30 days before (the dot on the bar);
- **month N of 12** since launch, counted live from `launch_date`.

Every table downloads as CSV.

## Publishing (every run, one product at a time)

| When | Command (from the skill folder) |
|---|---|
| Preview built, waiting for approval | `python scripts/dashboard.py publish --asin <ASIN> --run <run> --state proposed --label "Weekly run" --by "<name>"` |
| Apply verified and `log_invest.py` done | `python scripts/dashboard.py publish --asin <ASIN> --run <run> --state applied --label "Weekly run" --by "<name>"` |

| A product lined up for AI bidding (still on Scale Insights rules) | `python scripts/dashboard.py lineup --asin <ASIN> --by "<name>"` |
| Anything else that changed in the product file (brief, open items, activity, last 30 days, name), any product, any day | `python scripts/dashboard.py refresh --asin <ASIN> --note "<what changed>"` |

Add `--dry-run --out doc.json` to build without publishing.

**`refresh`** rebuilds everything that comes from the product file and keeps the latest run's tables (changes,
invest searches, search terms, harvest maths) from the live page, because run folders (`runs/`) are not in git.
So any teammate can update any page from the repo alone. A lined-up product is rebuilt whole, as `lineup` does. The
feed logs it as "Page refresh", not as a new run.

**`refresh --asin <ASIN> --run <run>`** (an AI-managed product's run folder, after its weekly run) also records that run in
the product file before it republishes: the run's SQP totals go onto `sqp_history` when they are for a newer week than its
newest entry (the last 26 are kept), and `data_stage` becomes the run's stage (a recorded "mature" stays). It refuses a run
folder planned for another product. `--dry-run` prints what it would record and writes nothing; `refresh` without `--run`
records nothing. Commit and push the product file after it, as after any publish (rulebook 10.6, weekly-run.md step 14.5).

### Two people, one page: the version guard

- Each product file has a `dashboard` block: the page `version` it last published or saw, with `published_at` and
  `published_by`. Every `publish`, `lineup` and `refresh` sends that version (header `X-Base-Version`).
- If someone else has published the page since, the server refuses with HTTP 409, saying who published and when.
  Nothing is overwritten. Fix: `git pull` (ask them to push if their change isn't there yet), then publish again.
- After a publish, the script writes the new version into the product file. **Commit and push it**, or the next
  person's publish is refused.
- `python scripts/dashboard.py list` shows, per product, whether your product file is in sync with the live page.
- `--force` skips the check. Use it only after you have checked what the other version changed.

A publish with `--state applied` also records `last_applied` in the product file.

### Lined-up products

- **Product file:** `registry` = `bid_owner` "Scale Insights", `stage` "queued", `queue` (onboarding order),
  `queued_on`, `run_by`, `onboard_on` (null until the run owner sets it); plus `brief`, `monitor`, `open_items`,
  `activity`. No run folder.
- **The page:** status pills, what's happening, price and profit, Last 30 days, open items, history. No invest
  table until onboarding. The home page lists these products under "Lined up for AI bidding", in queue order.
- **When onboarding starts,** the product file gains the onboarding fields (onboarding.md) and `registry.stage`
  moves to "onboarding", then "ai"; from then on it publishes with `publish`.

### The optimisation map (every product)

- **Where it comes from:** `config.json` → `scope`, one entry per lever of a product's ads (invest searches, other
  keyword bids, negatives, harvest bid, stop-loss, Scale Insights auto-negatives, 202 Brake, 201 harvest import,
  hours, price, other budgets, audience campaigns, auto and product targets, Sponsored Brands, Sponsored Display,
  listing).
- **Status by stage:** `ai` (optimised by the weekly run), `guardrail` (Scale Insights automation), `fixed` (held
  as set), `not_yet`, `si` (lined-up products: still on Scale Insights rules, described by `si_what`), `none` (not
  shown). Each lever has one status for AI-managed products (`ai` key) and one for lined-up ones (`queued` key).
- **"Changed" tags:** a lever's `types` are the plan's change types that count as a change to it. The latest run's
  counts show as "changed Oct 17 (282)".
- **Per-product exceptions:** in the product file, `"scope": {"<lever id>": {"status": "...", "what": "...",
  "note": "..."}}`. Example: a product whose Sponsored Brands bids a teammate manages by hand gets
  `"sb": {"status": "fixed", "note": "Managed by hand by <name> until <date>"}`.
- **When the workflow grows** (e.g. the weekly run starts pricing auto targets), change the lever's status in
  `config.json` once; every product's page follows at its next publish.

### Team mechanics (claims, activity, personal tokens)

| Command (skill folder) | What it does |
|---|---|
| `python scripts/dashboard.py claim --asin <ASIN> --what "Weekly run" [--until YYYY-MM-DD] [--force]` | Shows the team you are working on the product. A claim someone else holds is refused (HTTP 409) unless it is stale (past `--until`, or 7 days old) or you pass `--force` after talking to them. |
| `python scripts/dashboard.py release --asin <ASIN> --note "what was done"` | Ends the claim; the note goes into the activity feed. |
| `python scripts/dashboard.py note --text "..." [--asin <ASIN>]` | A line in the feed: a decision, a finding, a manual change. |
| `python scripts/dashboard.py team [--asin <ASIN>]` | Who is working on what, and recent activity. |
| `python scripts/dashboard.py login` | **Accounts (2026-10-25, decision 126).** The person signs this laptop in with their dashboard account, typing the email and password in their own terminal (never through an agent). The laptop key is saved as `PUBLISH_TOKEN`; every command here then runs under their name. `logout` ends it. `users list` / `users add --email --name --role` manage accounts (admins). Full guide: `docs/dashboard-accounts.md`. The old keys below work until Railway `LEGACY_KEYS=off`. |
| `python scripts/dashboard.py secrets --personal "Name"` | Old way (until `LEGACY_KEYS=off`): a teammate's own publish token; prints the hash for `PUBLISHERS`. Don't tell teammates to use it since 2026-10-25: they run `login`. |

- **Every publish is logged automatically** in the activity feed (who, which product, run label and state, and
  the doc's `activity_note`: the "Just changed" headline, or for lined-up products their 30-day numbers).
- **Who is "who":** with a personal token the server records the token's name, whatever `--by` says. With the
  shared token it records `--by`, else `PPC_DASHBOARD_BY`, else `PUBLISHER_NAME` in the secrets file.
  Checked live on 2026-10-17: the ten pages republished with Kim's personal token show "published by Kim".
- **Railway variable `PUBLISHERS`:** `Name:<sha256>,Other Name:<sha256>`. Add a teammate by appending their entry
  (MCP `set-variables`); remove one to revoke them. Kim's entry was added 2026-10-17.
- **Storage:** `/data/work.json` (claims), `/data/activity.json` (newest first, last 2,000 events) and
  `/data/reviews/<ASIN>.json` (the team's approve and decline decisions: append-only, kept beside the page, so a re-publish
  never loses one).
- **API:** `GET /api/work`, `GET /api/activity?asin=&limit=` (public, like the pages); `PUT|DELETE /api/work/<ASIN>`
  and `POST /api/activity` need a publish token. The two decision routes are in the next section.

### Per-row approvals: the server routes (added 2026-10-19)

| Route | Who may call it | What it does |
|---|---|---|
| `POST /api/reviews/<ASIN>/<itemId>` | **A personal token only.** The shared token and no token both get 403 "Sign in with your personal token to approve", because only a personal token says who decided | Records approve and decline decisions on the rows of one `human_review` item (`<itemId>` is the item's `id`, e.g. `bids-2026-10-24`). Body: `{"decisions": [{"row_id": "...", "decision": "approve" or "decline", "seen": {"current": 0.4, "new": 0.5, "new_capped": null, "budget_now": null, "budget": null, "tos_now": null, "tos": null, "modelled_spend_month": null}}], "note": "..."}`. `seen` is optional: the numbers the person saw on the row, each a number or null: the bids, and the budgets, top-of-search boosts and modelled monthly spend the card shows (fix E). Any other key is a 400; a key left out is stored as null. 1 to 500 decisions a call, note up to 1,000 characters. The page and the item must exist (404 otherwise). The whole batch is checked first: a bad entry is a 400 and nothing is written. It answers `{ok, asin, item_id, approved, declined, by, at}` and adds a line to the activity feed ("approved 3 bid changes") |
| `GET /api/reviews/<ASIN>` | Anyone who can view (public, like the pages) | Every decision ever made on the product, oldest first: `[{row_id, item_id, decision, by, at, note, seen}]` (`seen` only when sent). `[]` while there are none; 404 when the product has no page. The latest entry for an item and row wins |

- **A row_id is an opaque string.** The planner makes it and it may hold `:` and spaces. Never parse it.
- **Reading a product page** (`GET /api/products/<ASIN>`) merges each row's latest decision into the item as `decision`,
  `decided_by` and `decided_at`. The stored page is never rewritten, and published versions stay as published. The index
  (`GET /api/products`) does not merge decisions.
- **A decision belongs to its item.** A later item that reuses a `row_id` starts undecided.
- **`seen` is what makes an approval safe.** `dashboard.py approvals` applies an approval only when `seen` matches the row in
  the run's `plan.json` on every key (`SEEN_KEYS` in `scripts/dashboard.py`, the same list as `server.ts` and
  `bids-ui.js`): the bids, budgets and monthly spend to the cent, the boosts to the whole percent. A `seen` that leaves out a
  number the row has (an older client's, with the bids only) doesn't match. If the row was re-planned after the person
  looked, the approval is skipped and the reason names what moved ("saw budget $15.00/day, now budget $40.00/day").
- **Names:** `approvals` recognises the approval levels by the token's name: exactly "Kim" and "Lee" in `PUBLISHERS`
  (trimmed, ignoring case). Any other signed name counts as an owner.
- **Nothing is applied by a click.** A decision is only recorded. Rows reach Amazon when someone runs `approvals` and applies
  `approved/` ([weekly-run.md](weekly-run.md), steps 2 and 13).

### The Bids card: approve or decline each bid row (added 2026-10-19)

- **What the item is.** Each weekly run puts one Bids item per ASIN into Needs human (`kind: "bid"`, `id: "bids-<run date>"`),
  built from `plan.json` by `human_review.propose_bids`. In an enabled run it holds the rows for a person; in a shadow run
  it holds every row, each with the lane the planner chose. Who has to approve each row is on the row
  (rulebook.md, section 7.10). A newer run supersedes the older item.
- **Where the card appears.** Wherever the page draws a Needs human item (`humanItem` in `site/app.js`), a bid item gets the
  Bids card instead of the listing or price body. In the redesigned page the card sits inside the item's "Original note &
  evidence" fold (6b design note, 2026-10-19; not checked against the redesign, which is not committed here).
- **Sign in.** The card shows "Sign in to approve" with a password field for **your personal publish token**
  (`dashboard.py secrets --personal "Name"`; `docs/dashboard-personal-token.md`). The token is kept in the browser tab's
  `sessionStorage` (key `ppc.publishToken`) until you press "Sign out" or close the tab. It is sent only in the
  `Authorization` header when you press Approve or Decline. Without a token the rows still show, with "Sign in to approve or
  decline" in place of the buttons. A 403 clears the stored token and says "Use your personal token, not the shared one."
- **Approve and Decline.** One pair of buttons per row. The latest decision wins, so a person can change theirs. A click
  sends the decision with `seen` (the numbers on screen) to `POST /api/reviews/<ASIN>/<item id>`. The row then says
  "Approved by Lee, 14:05 SGT". An error shows the server's words in the row. There is no "approve all" button.
- **What each row shows.** The search, the change in plain words, "now → new" (a capped raise reads "proposed $0.62; the +25%
  cap, approving writes $0.37"), orders and clicks (90 days), how sure, opportunity ("not scored" without volume), why, and
  who must approve.
  - "Now → new" also shows what a row commits beyond its bid (fix E): "Budget $10.00 → $15.00/day · top of search 0% →
    50%" ("50% (kept)" when it stays), and for a new campaign "New campaign at $0.88, $10.00/day (about $300/month)" (a
    reused one "Reused campaign at ..."; "(monthly spend not modelled)" when the plan has none). Every number shown is in
    `seen`.
  - Who must approve is "Book owner" or "Kim" on every row since 2026-10-22 (rulebook 7.10). An approval from someone
    below the row's level is recorded, and the row then says "Recorded; needs Kim's approval to apply" (names compared
    as `approvals` compares them). A row a decline holds asks for the decliner's level too (rulebook 7.8), so a row
    Lee declined says Lee ("Recorded; Lee's decline stands unless Lee approves").
- **Shadow runs.** The card says "Shadow run: nothing here applies on its own. Each row can be agreed or refused." Approve
  means agree, Decline means refuse. These were the counts behind the Nov 9 gate (rulebook.md, 7.11), superseded when decision 98 turned Auto on for every AI
  product; a shadow run now means a product whose Auto is off.
- **Held rows.** A row a person's earlier decision or a rank experiment holds says "Decided by <lock_by> on <lock_on>:
  <lock_decision>; holds until <locked_until>" (or "Held by a planned rank experiment until <date>"). A bid or pause row can
  still be approved again, which is a new decision. On any other held row Approve is not offered ("Held until <date>:
  approving can't apply until the hold ends"); Decline is.
- **Closed items.** A superseded, dismissed or resolved Bids item drops its rows for one line ("N rows: counts by lane.
  Superseded or closed on <date>; the rows are kept in the run's plan.json."), with no buttons. The run's `plan.json` keeps
  the rows.
- **Known gaps (2026-10-19).**
  - The "Review type" filter has no Bids choice, so a bid item shows under "All reviews".
  - Page copy such as "Read-only team view" and "No automatic listing or price changes" is unchanged. Updating it waits for
    Kim's OK and the merge with the redesigned page.
  - The card makes one `GET /api/reviews/<ASIN>` per product with open bid cards, to show decisions made earlier. The index
    doesn't carry them.
  - The card can't show your name before you decide: the server names the personal token only on a decision.
- **Not live yet.** The card and the server's `/api/reviews` routes are built and tested, but not deployed or published: both
  need Kim's OK. Until then, runbook step 0 holds ([weekly-run.md](weekly-run.md)).

### The apply-side commands (added 2026-10-19)

These read the dashboard and write local files and the product file. None of them writes to Amazon. The weekly order is in
[weekly-run.md](weekly-run.md); the folders they work on are in map-playbook.md.

| Command (skill folder) | What it does |
|---|---|
| `python scripts/dashboard.py reviews --asin <ASIN> --save <run>/reviews.json` | Saves the team's decisions (`GET /api/reviews/<ASIN>`) as `{asin, saved_at, entries}`. `plan.py` turns every decline in it into a lock, and refuses to plan without it whenever the product file holds a Bids item |
| `python scripts/dashboard.py approvals --asin <ASIN> --run <run> [--live <file>] [--dry-run] [--discard-unapplied]` | Turns the approvals on the run's Bids item into `<run>/payloads/approved/*.json`, and each decline into a lock in the product file's `decisions`. Runs any day; non-calendar execution guards remain. `--live` leaves out rows whose live bid or state moved since the plan |
| `python scripts/dashboard.py applied --asin <ASIN> --run <run> --folder auto\|review\|approved [--date <day>] [--dry-run] [--now <ISO UTC>] [--rows "<row_id>,..."] [--record-anyway]` | `--dry-run` is the check before an apply; it runs any day and retains non-calendar guards (`--now` sets the clock for tests). Without it, records that the folder went out: its rows join `payloads/applied_rows.json`, approved rows get an approve lock, creations a create lock. `--rows` records only the rows that went out when an apply stopped part way |

### For Growth: the tab, the status route and the Growth keys (added 2026-10-22)

The Growth team's listing passes. The item, its rules and its block are in [for-growth.md](for-growth.md); this is what
the dashboard does with it. Built and tested on 2026-10-22 (branch `claude/for-growth-4ff698`), **not live**: see "Going
live" below.

- **The tab.** `#/for-growth`, a "For Growth" entry in the top navigation with the number of items not closed. Four
  groups:
  - **Due or flagged:** an open item (not picked up yet) whose `growth.due` date has arrived (or has none), or that is a
    rotate-out flag.
  - **Open:** picked up or copy pushed (a rotate-out flag too), waiting for the listing change, and an open item that is
    not due yet.
  - **Scheduled:** every product with a next-pass window and no item that is not closed, the soonest `by` date first,
    with both dates, how far off the later one is and the anchor. A product that is not enabled is listed with "Not
    enabled: no block is raised until it is switched on". There is no card, because there is no block yet.
  - **History:** resolved and dismissed passes, newest first, the block folded.
  **Status filters (Kim, 2026-10-28).** On the tab the menu's second row holds All open, Not picked up, Picked up
  and Copy pushed, each with its live count (`#/for-growth/not-picked-up`, `#/for-growth/picked-up`,
  `#/for-growth/copy-pushed`); the same three counts sit under the tab's heading as links. A filter shows only the cards
  in that status (closed items are in none), newest first, and Picked up and Copy pushed say who holds them ("By person:
  Kris 2 · Kat 1"). The counts follow the 20-second poll, so a teammate's click moves them. The For Growth nav entry's
  tooltip gives the same split.
  A line at the top counts stale items: open or picked up for `growth.stale_days` (45) days without moving on. It is a
  count and nothing more.
- **The card**, on the tab and in a "For Growth" section of the product page: the pass tag (first or second), the status,
  the product and an "On Amazon" link, when it was produced and what triggered it, the stage line, the anchor and due
  dates (and the window), the data window, then the block: one **Copy block** button copying the whole markdown block
  (`growth.block_md`) so Growth pastes it into their Claude unchanged, the block in a `<pre>`, and the swap, rotate-out
  and offer tables and the notes rendered from `growth.block`. A blank cell reads "unknown", never 0. The status line
  names who and when ("Picked up by Robin, Nov 21, 10:05 SGT"); a closed card folds its block and tables and shows the
  AI's proof. A banner says so when the run read no listing. The card is drawn once per page, in the For Growth
  section: wherever a page draws review items through `humanItem`, a growth item is one line pointing to that section,
  with no buttons, and since main's page reconcile (2026-10-22, 21:27 SGT) the folded Context & audit draws no review
  items at all (its follow-ups list skips the growth item, as the Needs-human queue does).
- **The product page's For Growth section** also carries, from day 0 and before any item exists, a line from
  `card.growth = {enabled, anchor, next_pass}`: "First listing pass due <date> (anchor: ...)" before the first pass,
  "Listing pass: no earlier than <date>, by <date>" after one, "not enabled for this product", or "no date yet, because
  the anchor is not known". The card is read-only on an earlier version of a page. `card.growth` is also in the index
  (`/api/products`), which is how the tab's Scheduled group reads every product's dates without fetching each page.
- **The two buttons.** **Picked up** and **Copy pushed**, forward only (an open item offers both, a picked-up item offers
  Copy pushed, a pushed item waits for the AI's close). They are disabled without a key. Sign-in is the Bids card's: the
  key is kept in that browser tab's `sessionStorage` (`ppc.publishToken`), sent only when a button is pressed, and a 403
  clears it. After a click both buttons stay disabled on every card of that product until the page is reloaded. An
  optional note (up to 1,000 characters) goes with the click. For Growth members: [docs/growth-dashboard-login.md](../../../../docs/growth-dashboard-login.md).

The server (`dashboard/server.ts`):

| Route | Who may call it | What it does |
|---|---|---|
| `POST /api/items/<ASIN>/<itemId>/status` | **A personal `PUBLISHERS` token or a `GROWTH_PUBLISHERS` key.** The shared token and no token get 403 "Sign in with your personal token to update this item", because only a named key says who clicked | Body `{"status": "in_progress" or "copy_pushed", "note": "..."}` (`note` optional, blank stored as null). Any other status is a 400 (`resolved` is the AI's alone, set through the product file); an item that is not a For Growth item is a 400 "Only a For Growth item takes a status here"; an unpublished page or an unknown item is a 404. It appends `{item_id, status, by, at, note}` to `items/<ASIN>.json` beside the page, adds one activity line ("picked up ..." or "marked copy pushed on ...") and answers `{ok, asin, item_id, status, by, at}` |
| `GET /api/items/<ASIN>` | anyone who can view | every entry, oldest first (`[]` while none; 404 when the product has no page). `dashboard.py reviews --save` reads this |

- Reading a product page (`GET /api/products/<ASIN>`) adds `item.status_latest = {status, by, at}` to each item with an
  entry. The item's own status stays as published, the stored page is never rewritten, and the index does not carry
  `status_latest`.
- **`GROWTH_PUBLISHERS`** is a Railway variable in the same format as `PUBLISHERS`: `Name:<sha256>,Other Name:<sha256>`,
  names of letters, digits, spaces and `. _ -` (up to 40). **A Growth key can reach the status route and nothing else:**
  every other write route answers it 401 (the approve route 403, as for any key that is not a personal token), it is not
  a publisher, it never counts as an approval level, and it does not open a page that needs the viewer password.
  Removing a key's entry revokes it.
- **Issuing a key** (Kim or Lee, from the skill folder): `python scripts/dashboard.py secrets --personal "<Name>"
  --role growth`. The key is written to its own private file beside the secrets file
  (`~/.config/your-ppc-repo-dashboard/growth-<name>.env`, `ROLE=growth`) and is **never printed**; the command prints
  only the `GROWTH_PUBLISHERS` entry (`Name:<sha256>`, a hash, safe to send). The issuer opens that file and hands the
  key over privately. The names Kim and Lee are refused (they are approver names). `--force` makes a new key for a
  name that has one (then replace its entry). A `ROLE=growth` file cannot be used as a publishing secrets file: the
  script refuses it. The four steps, for the Growth team: [docs/growth-dashboard-login.md](../../../../docs/growth-dashboard-login.md).
- **The commands** that touch the item (all change the product file only; none publishes or writes to Amazon):
  `dashboard.py reviews --asin <ASIN> --save <run>/reviews.json` (also saves the clicks as `<run>/item_statuses.json`),
  `growth --asin <ASIN> --anchor`, `--enable`, `--disable` and `--emit`, and `secrets ... --role growth`. What each does,
  and how `publish` moves the clicks onto the item and closes a pass on a listing change: [for-growth.md](for-growth.md),
  "Lifecycle" and "Commands".
- **Going live (Kim's decisions, in this order).**
  1. After the branch is merged, deploy `dashboard/server.ts`, which holds the status route (Railway MCP
     `update-function-source-code`, the whole file, with Kim's OK). Until then the route does not exist on the live
     server: `reviews --save` warns that the statuses were not saved and saves the decisions as before.
  2. Put the built page live: `app.js` and `app.css` only ("Changing the page or the server": never `dashboard.py
     site`, and never an upload from a branch). The safe way: download the live `app.js` and `app.css` into a scratch
     folder; run `python dashboard/build_growth_ui.py --site <that folder> --overview <a scratch copy of
     overview-ui.js>` (so the repo's copy is not touched); check that the only difference from live is the For Growth
     block (its markers and the six marked lines); upload just those two files; read them back. On 2026-10-22, about
     21:55 SGT, main's `site/app.js` and `app.css` equalled the live files (main's reconcile of 21:27 SGT,
     `logs/2026-10-22-dashboard-source-cleanup.md`) and the builder applied cleanly to a live copy (+469/-0 lines on
     `app.js`).
  3. Issue the Growth keys (Robin, Kat, Kris) and add their entries to `GROWTH_PUBLISHERS` on Railway.
  4. Enable products one at a time in Kim's order, the gel pens and the bookmarks pilot first: anchor, then
     `growth --enable` ([weekly-run.md](weekly-run.md), "For Growth: the anchor and the switch").
  Until step 4, nothing raises an item.

### The monitor block (every product)

Write it before publishing, from Scale Insights `get_sales_data` for the 30 days to yesterday:

```json
"monitor": {"start": "2026-09-17", "end": "2026-10-16", "as_of": "2026-10-17", "source": "Scale Insights sales data (get_sales_data), synced …",
            "sales": 791.12, "orders": 85, "units": 88, "ad_spend": 198.67, "ad_sales": 90.90, "acos": 2.1856,
            "breakeven_acos": 0.3794, "tacos": 0.2511, "organic_share": 0.8851, "profit": 33.90, "refund_rate": 0.0341}
```

Ratios are fractions. `breakeven_acos` = the product file's `profit_per_unit ÷ price` (Scale Insights' own
breakeven uses its list price, which can lag a price change). Refresh it every weekly run.

### Organic rank (DataDive Rank Radar, daily)

- **Page section "Organic rank on the main searches"** (product page, after "Last 30 days"): the invest and prove-first
  searches first, then the radar's biggest relevant searches, up to 12. Per search: a 30-day line of the daily organic
  rank (#1 at the top, log scale, dashed line at #10, upright line on the day the AI took over), the latest rank, the
  move against 7 days before, the move since the AI took over, and the best rank. The card on the home page says how
  many main searches are in the top 10 and how many moved up or down in 7 days.
- **Update it daily** (or at least at each weekly run): pull `get_rank_radar_data` for the product's `rank_radar_id`
  (30 days to today, `pageSize` 100, every page) into the run folder, then
  `python scripts/dashboard.py rank --asin <ASIN> --radar <run>/radar_p*.json --by "<name>"`.
  It stores the block in the product file (`rank`) and refreshes the page; commit and push the product file.
- A new radar has no readings until DataDive's first daily crawl, so the section says so and fills one day at a time.
  Products without a radar say "No Rank Radar yet".

### Singapore time (2026-10-18, Kim's request)

- Every time and date on the dashboard is Singapore time (SGT, UTC+8): timestamps, "today" and "yesterday", due dates
  and the day folds. The footer says so.
- Write new activity times in SGT ("about 09:30 SGT"). Older lines carry UTC ("about 16:50 UTC"): the page moves a
  dated line to its Singapore date. In prose, a time that crosses midnight moves the date next to it ("Oct 17, about
  16:50 UTC" reads "Oct 18, about 00:50 SGT"; "after 16:00 UTC on Oct 18" reads "after 00:00 SGT on Oct 19"); a
  nightly run's time ("its 18:10 UTC run") just converts; any other crossing time says "(next day)". A bare ISO date
  in prose reads "Oct 17"; dates inside file names stay as written.

### Interface rules from the Oct 18 design pass (impeccable, taste, Emil Kowalski, frontend-design)

- One identity: YourBrand teal and gold, Montserrat for headings only, Source Sans for everything else. One radius
  system: containers 10px, controls 8px, pills and tags round.
- No label above a heading; the heading speaks for itself. IDs go on a quiet line under the product name.
- Lists (open items, coming up, activity, the goal board) are one surface with hairline rows, never a card per row and
  never cards inside a fold. Done items are muted.
- Markers are drawn in CSS: chevrons for links and folds, triangles for up and down, a short rule for an empty value
  (read as "none"). No arrow characters, no decorative dots, no dash characters in copy or date ranges ("Sep 17 to
  Oct 16").
- Motion is feedback only: 150-160ms with a strong ease-out, a 0.97 press scale on buttons, hover effects only on real
  pointers, all of it off under reduced motion.
- "On this page" is one row of short labels (`JUMP` in app.js); it scrolls sideways on a phone.

### Re-evaluation 2026-10-18 (impeccable critique, two independent reviews; ui-ux-pro-max checked)

Scored 25/40 before the fixes (detector: 3 findings, all false positives: the brand font and the CSS triangles).
Fixed the same day:
- the jump row landed headings under the sticky header; it now scrolls to just below the header and its own row;
- SGT conversion left dates a day behind (see Singapore time above);
- red is for money lost only: not for being past month 12, not for the breakeven click tile;
- keyboard focus ring in the darker gold edge (#a87e00, about 3.7:1 on white; the bright gold was about 1.6:1);
- "Type of change" tabs stay boxed; "Bid role" chips are small round pills; on phones each is one sideways row;
- rows that scroll sideways fade at the right edge only while more is hidden there;
- an empty value inside a joined cell ("#12 · none") uses the drawn marker; the invest table's organic rank falls
  back to Rank Radar;
- long values in key-value cards stop at 75 characters; "What's happening" at 64ch;
- the skip link no longer sends a product page home; an unknown ASIN says so, with its own tab title.

Second pass the same day: section and filter links (above), compact change and invest tables on phones, column
notes under tables, and the claim instructions in plain words with the command in small type.

ui-ux-pro-max (installed 2026-10-18) was judged not useful for this page: its design-system generator proposed a
scroll-storytelling layout, a pink palette and Playfair for an internal operations dashboard, and its UX and chart
rows are generic. Its one fitting rule, kept here: fewer than 4 data points is a number, not a chart.

### Lookback windows and date folds (2026-10-17)

- Every sales figure names its window: "last 30 days, Sep 17 – Oct 16, 2026", and the trend arrows name the window
  they compare with. The window comes from the product file's `monitor.start/end` and `monitor.prior`.
- Changes are folded under their date ("Oct 17, 2026 · Launch (onboarding), applied · 337 changes"); click the date to
  open them. The same applies to "Latest on this product" and the history.

### Update the product file before publishing

The page reads these fields from the product file. Keep them dated and in plain words:
- **`brief`:**
  - `as_of`;
  - `headline`: one line, shown on the home page card;
  - `happening`: 2–3 sentences, with real searches and dollar figures and their dates;
  - `steps`: 3–4 next steps, each with its date.
- **`open_items`:** each has `opened`, `due`, `status` (`open`, `decision` or `done`), `short` (the label for
  date lists) and `text`. Sam finished items `done` rather than deleting them.
- **`activity`:** one dated line per applied change, with the change set IDs in `ref`.
- **`registry`** (`bid_owner`, `owner_since`, `run_by`, `weekday`, `next_run`) and **`reviews`:** update them
  when the dates move.
- **`harvest.active`** and **`harvest.strategy_status`:** update them when the harvest state changes.

### When the apply deviated from the plan

Write `<run>/applied.json` before publishing:

```json
{
  "approved_by": "Kim",
  "change_sets": [["Bids", "4eeb0813"], ["Run log", "logs/<date>-<product>-weekly-run.md"]],
  "notes": ["One line per deviation, in plain words."],
  "skipped": [{"type": "Negative exact", "keyword": "...", "ad_group_id": "...", "why": "..."}],
  "retype": [{"type": "New exact campaign", "keyword": "...", "to": "Reuse exact campaign", "campaign_id": "...", "note": "..."}],
  (a retype row with "keyword_id" changes only that keyword's row, e.g. {"type": "Bid change", "keyword": "...", "keyword_id": "...", "new": 0.57, "note": "corrected after the apply"}),
  "extra": [{"type": "Bid change", "keyword": "...", "current": 1.3, "new": 0.35, "why": "...", "note": "..."}]
}
```

- `extra` rows use the plan.json change format.
- `--due-plan <later plan.json>` adds a "fix due next run" column to the invest table. The launch used it for the
  corrections found on 2026-10-17.

### Run logs on the dashboard (added 2026-10-21, Kim's request)

The repository's `logs/*.md` are also served by the dashboard, so a teammate or an LLM reading only the dashboard sees
the record of what was done, not just the activity feed and the page versions.

| Where | What |
|---|---|
| `/logs` | a plain index page, newest first (names start with the date) |
| `/logs/<name>.md` | the log as text |
| `GET /api/logs` | JSON: `[{name, bytes, sha256, updated_at, by}]` |
| `GET /api/logs/<name>.md` | the markdown (`text/markdown`) |
| `PUT /api/logs/<name>.md` | publish one (any publish token; the body is the markdown; same content changes nothing) |
| `DELETE /api/logs/<name>.md` | remove one (publish token) |

Publish them with `python scripts/dashboard.py logs --push` (every `logs/*.md` at the repository root; unchanged files
are skipped by SHA-256; one activity line sums up the push), `--push <files or globs>` for a few, `--list` to see what
the dashboard holds, `--dry-run` to see what would go. Run it at the end of every run, after the run log is written
(weekly-run.md step 13). The repository stays the source; the dashboard is the copy. Names must be `<name>.md` with
letters, digits, `.`, `_`, `-` only; a log is at most 2 MB.

## Secrets

- **Create:** `python scripts/dashboard.py secrets --init` creates the secrets file and prints only the two
  hashes. `--hashes` prints them again.
- **Rotate:**
  1. Run `secrets --init --force`.
  2. Set both hashes on Railway: MCP `set-variables` on the ppc-dashboard service, as `DASHBOARD_PASSWORD_SHA256`
     and `PUBLISH_TOKEN_SHA256`.
  3. Share the new password (only matters if public viewing is switched off).
- **Who needs what:**
  - A teammate who publishes needs `PUBLISH_TOKEN` in their own secrets file, or in the `PPC_DASHBOARD_TOKEN`
    environment variable.
  - Viewers need only the link while `DASHBOARD_PUBLIC` is on; otherwise the password.
  - The skill folder never holds secrets, because it is committed to the your-ppc-repo repo and shared.
  - A For Growth member needs a Growth key (`secrets --personal "<Name>" --role growth`, a hash in `GROWTH_PUBLISHERS`),
    which only marks For Growth items. It is handed over privately and pasted into the card
    ([docs/growth-dashboard-login.md](../../../../docs/growth-dashboard-login.md)).

## Changing the page or the server

- **The page:**
  - Edit `dashboard/site/*`, then run `python scripts/dashboard.py site`. No redeploy is needed.
  - **Reconciled 2026-10-22:** the unpublished research panel, stage filters and research-count links are removed
    from `site/app.js`, along with their CSS. The fallback human queue accepts only human-ready recommendations
    and bid decisions, including when an old research-stage URL is used. Research stays in product records.
    The 50%+ organic and profitable-after-ads goal rule is preserved. See
    `logs/2026-10-22-dashboard-source-cleanup.md` for validation and deployment evidence.
  - `dashboard.py site` uploads every site file, so run it only from a checkout whose `dashboard/site/` is what you want
    live. A checkout older than the live page would replace it. Until the redesigned page is committed and merged here,
    publishing the Bids card needs Kim's OK and an upload of `app.js` and `app.css` only.
  - Data values are written with `textContent` only. Keep it that way.
  - **The Bids card is built into `app.js` and `app.css` by `dashboard/build_bids_ui.py`, not edited there.**
    - The source is `dashboard/bids-ui.js` and `dashboard/bids-ui.css`. The script copies them in between marker
      comments (`BIDS_UI_START` to `BIDS_UI_END`, and `BIDS_UI_STYLES_START` to `BIDS_UI_STYLES_END`), plus one guard line as
      the first statement of `humanItem`: `if (item.kind === 'bid') return bidsItem(item, card);`. Nothing else in either
      file changes, so every other view renders as before.
    - **Re-run it after any rebuild or replacement of `app.js` or `app.css`** (for example when the redesigned page is
      merged): `python dashboard/build_bids_ui.py` (or `--site <folder>` for another copy of the site). `--check` changes
      nothing and exits 1 when the site is not up to date. Running it twice changes nothing.
    - Edit the two source fragments, never the injected blocks. Test with `node dashboard/test_bids_ui.mjs`.
  - **The For Growth tab and card are built the same way, by `dashboard/build_growth_ui.py`** (2026-10-22). The sources
    are `dashboard/growth-ui.js` and `growth-ui.css`; it copies them into `app.js` and `app.css` between `GROWTH_UI_START`
    and `GROWTH_UI_END` (and the styles' markers), plus seven marked single lines at named anchors (the guard in `humanItem`,
    the nav entry, the tab's status row in the menu's second row, the route and its dispatch, the Needs-human queue guard, and the product page's section). It needs the
    Bids card built first (it reuses its sign-in), changes nothing else, and does nothing on a second run.
    `python dashboard/build_growth_ui.py --check` changes nothing and exits 1 when the site is not up to date. Re-run it
    after any rebuild or replacement of `app.js` or `app.css`, after `build_bids_ui.py`. Edit the fragments, never the
    injected blocks. Test with `node dashboard/test_growth_ui.mjs`.
- **The server:**
  - Edit `dashboard/server.ts`. Railway functions are limited to 96 KB.
  - Test with `node dashboard/test_server.mjs dashboard/server.ts`.
  - Deploy with the Railway MCP `update-function-source-code`, passing the whole file. The volume keeps the data.
- **Local preview** (Deno), with test secrets and the server adding the sign-in itself:
  `deno run --allow-net=127.0.0.1:8787 --allow-read --allow-write --allow-env dashboard/serve_local.ts file:///<skill>/dashboard/server.ts <skill>/dashboard/site <doc.json> ...`.
  Then open http://127.0.0.1:8787.

## Limits

- Viewing is public (no logins), so the page can't tell who viewed it, and anyone with the link sees the
  products' economics. It holds no credentials. Switch `DASHBOARD_PUBLIC` off to restrict it again.
- Viewers can't approve or comment on the page. A teammate with a personal token can approve or decline a bid row on the
  Bids card, which only records the decision; the rows reach Amazon when someone applies them (weekly-run.md). Everything
  else still goes through the run owner, in the session that built the preview.
- The personal token is pasted into the page and kept in that browser tab's `sessionStorage` until you sign out or close the
  tab (`docs/dashboard-personal-token.md`). Use it on your own laptop only.
- The page shows what was published. It does not read Amazon live, so check the "Published" time in the footer.
