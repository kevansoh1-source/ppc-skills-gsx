# The AI bidding rules today (plain words)

For PPC teammates and their Claude Code or Codex. Updated 2026-11-04, after decisions 182 to 186 (174 to 178 on Oct 31).

This page lists **the rules as they stand today**, without the history. The full rulebook, with every detail and the dated
reason for each rule, is `.claude/skills/amazon-ppc-ai-bidding/references/rulebook.md`. Every number lives in that
skill's `config.json`. When the two pages disagree, the newest dated decision in `docs/decisions.md` wins; please fix
whichever page is behind.

Other pages:
- What changed on Nov 4: [whats-new-2026-11-04.md](whats-new-2026-11-04.md). On Oct 31: [whats-new-2026-10-31.md](whats-new-2026-10-31.md).
- Why it works this way: [background.md](background.md).
- What to type: [run-ai-bidding.md](run-ai-bidding.md).
- What to do when a run stops: [ai-bidding-field-guide.md](ai-bidding-field-guide.md).

## 1. The goal

- **Rank, then hold about half of each product's units organic.** That's about 50% organic and 50% from ads, at about
  breakeven, within roughly 12 months of launch (decisions 1, 4 and 143).
- **Ranking takes 10 to 12 months on Amazon.** Rank searches are judged slowly, on organic results (decision 142).
- **Losses on rank searches are the investment.** Money figures are information, not a cap (decisions 99, 100 and 174).

## 2. How good is a search for us? The index

**Index = our conversion ÷ the market's conversion on the same search.**
- Our conversion comes from SQP: all our clicks, ads and organic. When SQP is thin, it comes from the ads search-term report.
- The market's conversion comes from SQP: all sellers on that search.
- Thin numbers are pulled toward the market, so one lucky order can't make a search look like a winner.

How to read it:
- **1.1 or more:** beats the market.
- **0.8 to 1.1:** about the same as the market.
- **Under 0.8 on 15+ clicks:** trails the market.

**Orders** count as the higher of the search's SQP purchases and its ad orders, never the two added together. SQP
already includes the purchases that came through ads (decision 174).

## 3. What each search gets (its role)

**Rank searches.** We invest in these to climb organically:

| Role | When | Bid | Campaign |
|---|---|---|---|
| **Invest** | Relevant, index 1.1+, 150+ searches in 12 weeks but no more than 3,000 a month (4,000 at index 1.3+; decisions 182 and 189), 3+ orders | Amazon's suggested median, or breakeven if higher, never above Amazon's suggested high | Its own exact campaign, $10/day ($15 on the biggest), top of search +50%, plus its SB video |
| **Prove first** | Index 1.1+ and 2+ orders, but not yet Invest (decisions 174 and 178); the same 3,000-a-month cap (4,000 at index 1.3+) | Same as Invest | Its own single-keyword exact campaign, $5/day, top of search +30%, plus its SB video. 3 orders at 1.1 makes it Invest; about 30 clicks with no order makes it Trim |

**The rank volume cap (decision 182, Nov 4; seasonal products too, decision 185; 3,000 since Nov 5, decision 189).** A
search with more than 3,000 searches a month is never a rank search, unless we convert on it at 1.3 times the market or
better: then the line is 4,000. If it beats the market it bids as Defend, and a rank search already above its line steps
down at the next run. The run cross-checks the volume (Kim, Nov 4): it takes the highest of Scale Insights' count,
DataDive's Rank Radar volume (from the product file) and SoldScope's when the run has it, each read as it is (no 0.8
conversion since Nov 5), so a search one source undercounts is still capped. Why: across 263 rank searches on 66
products (Oct 2026), rank moved on searches of 500 to 2,000 a month (41 up, 28 down) and not on bigger ones (2,000 to
10,000: 15 up, 18 down; over 10,000: 7 up, 10 down, none into the top 10), while searches we didn't invest in moved
evenly. Details: [rank effort by search size](../knowledge/rank-effort-by-search-size-2026-11-04.md).

**Seasonal products too (decision 185, Kim, Nov 4: "Yes, cap seasonal too").** A season rank search over the cap is
not invested in during the rank build either: it bids as Defend, its exact keyword at the suggested low (never under
breakeven, top of search 0%). Its size is the highest of the usual sources and the season curve's peak week × 52/12
(SoldScope weekly searches, the season block). Season rank searches under the cap keep investing as before.

- **A big search keeps some visibility.** A search over the cap that beats the market bids its exact keyword at the
  **suggested low** (Amazon's; SoldScope's if Amazon has none), never under breakeven and never raised, with top of
  search at 0% (Kim, Nov 4: "cut to amazon's suggested low .. instead of breakeven").
- **Low and mid first, big later** (Kim, Nov 4): invest in low (under 2,000 on DataDive) and bottom-mid searches first,
  build up reviews and variations, then go for bigger searches. When a product's listing is ready, a person raises its
  own cap in its product file (`rank_max_monthly_searches`: 5,000, then 10,000), and its
  next run invests in the bigger searches it beats the market on.
- **Every product is on Auto** (Kim, Nov 4: "i want all ASINs to be on auto"). The rules above keep spend in check; no
  money caps, no budget cuts.

**Ordinary keywords.** These are everything that isn't a rank search (decisions 157 and 175):

| Role | When | Bid |
|---|---|---|
| **Hold** | Index 0.8 to 1.1 | 100% of its breakeven click (profit per order × its conversion) |
| **Defend** | Index 1.1+ but small, or already 10%+ impression share and 50%+ organic | 100% of breakeven |
| **Test** | Not enough evidence yet, but 150+ searches or 1+ ad order | Breakeven at the market's conversion: at least $0.35, never above its own breakeven |
| **Discovery** | Broad, phrase and auto keywords | Breakeven at the conversion of the searches it actually served |
| **Trim** | Index under 0.8 on 15+ clicks | 70% of its own breakeven (at least $0.10). Paused under 0.5 on 30+ clicks |
| **Top-10 rule** | Any ordinary keyword on a search we already rank top 10 for organically (Rank Radar's 14-day median, or SQP when there is no radar) | 75% of breakeven. Rank searches keep investing even in the top 10 |
| **Negate** | Irrelevant to the product | Paused or negated, through the negative audit's approval |
| **Brand** ("yourbrand ...") | Always | Organic only: cut, never bid up (decision 141) |

Organic share is reported on every run, but it no longer changes a bid. The cut to 70% for products under 50% organic is
gone (decision 175).

**The suggested mid (decision 177; Sponsored Products exact only since decision 183, Nov 4).** Two kinds of ordinary
**exact** keyword bid Amazon's suggested **middle** bid instead of breakeven, so they keep being seen. Broad and phrase
keywords, product targets and every Sponsored Brands keyword bid their role's price (breakeven) instead: on cheap
products the mid was far above what a click is worth, and broad and phrase at the mid lost money while exact converted
well (the Nov 4 visibility test, now the rule for every product):

| Which keywords | Bid |
|---|---|
| **Validated:** a Hold keyword (index 0.8 to 1.1) whose search has 2+ orders. Also a Test or Discovery keyword with 2+ orders at index 0.8 or more | The suggested mid, even when it is above or below breakeven. Never the low or the high. No top-of-search boost and no rank campaign of its own |
| **Launch test:** a Test or Discovery keyword with 0 or 1 orders of its own | The suggested mid while it is tested (see below) |
| Either kind, on a search we already rank top 10 for | 75% of the mid |

How long the launch test runs (decision 178): long enough to expect **2 orders** at the product's own ad conversion. A
product that converts 10% of its ad clicks gives a new keyword 20 clicks; one that converts 5% gives it 40. Never fewer
than 15 clicks and never more than 60. The leak check doesn't pause a keyword while it is in its test.
- **0 orders at the end of the test:** it drops back to its normal price (breakeven, or Trim), and the leak check may
  pause it.
- **1 order:** more clicks at the mid, until 3 expected orders (30 clicks at 10%, 60 at 5%, never more than 90). Still only
  1 order then, it goes back to its normal price.
- **2+ orders:** it is validated. Index 1.1+ goes to Prove first (its own rank campaign) when the search has 150+ searches.
  Otherwise it stays at the mid. Under 0.8 goes to Trim.

Where the mid comes from, in order: **Amazon's suggested median** for that keyword; if Amazon is rate-limited or has none,
**SoldScope's** middle cost per click; if neither has one, the **closest estimate** (the keyword's own cost per click, or
the middle of Amazon's mids on the product's other searches, whichever is higher). With none of those it keeps its normal
price. When a keyword is in two campaigns, only the copy with the most clicks bids the mid. A Sponsored Brands keyword (the AI's
own video campaigns) bids its search's Sponsored Products mid, at the same share a rank search's Sponsored Brands bid uses
(100% today).

Not covered by the mid: rank searches (they invest as above), Defend, Trim, B2B and audience (AMC, low-bid) copies, brand
searches, paused keywords, and seasonal products while in season (they bid breakeven). Each run's summary lists every
keyword at the mid, where its mid came from and what it has spent, plus the launch tests that ended (`summary.mid_bid`).

## 4. Money and budgets

- **No money cap on rank searches** (decisions 99, 100 and 174).
  - The $2,000 a month a product guide and the $60 a month loss line for one search are flags in the summary and the
    Slack message. Nothing is parked, held or shrunk because of them.
- **Budgets are never cut to save money.** Kim: "cutting budget doesnt help the advertising".
- **Budget steps:**
  - A **rank campaign** that runs out of budget on 5+ of the last 14 days steps up +50% (at least $1), up to $50 a day,
    then waits a week before it's looked at again. This happens whatever its ACOS, and it is never stepped back for
    ACOS (decision 174).
  - An **ordinary campaign** that runs out of budget steps up only when it has 3+ orders and its ACOS is at or under 80%
    of the product's breakeven ACOS. A step that stopped paying goes back.

## 5. Placements

- **Top of search:**
  - Invest campaigns: +50%.
  - Prove-first campaigns: +30%.
  - Every other campaign: 0%, including the old "TOS 900%" campaigns (decision 155).
- **Product page base bid and down-only bidding:** where there's enough placement data, the best-converting placement
  keeps the bid and the others bid by their own conversion. Campaigns move to down-only bidding (decision 140). This can
  give an ordinary campaign a top-of-search modifier (the base bid drops, the better placement is raised back), and that's
  allowed: no placement bids more than its price, and it applies without asking.
- **Where a boost can't come off this run**, the bid is priced as price ÷ (1 + boost). That way a top-of-search click
  never costs more than the price.

## 6. The brakes

1. **Stop-loss**, for rank searches (decision 142).
   - It looks at each invest search at months 3, 6, 9 and 12 of investing, on organic rank (Rank Radar) and organic
     purchases only.
   - If neither improved, the search steps down to Hold.
   - B2B keywords use their own 4- and 6-week checks.
   - **Index slip (decision 182, Nov 4).** A rank search that now converts under 0.8 of the market on 15+ of our clicks
     doesn't wait for month 3: it steps down at the next run, the same way (its bid at or under breakeven, top of search
     0%, the $5 Hold budget), and leaves the invest list once that has gone out.
2. **56-day cool-off.** A search the stop-loss stepped down isn't promoted again for 8 weeks.
3. **Weekly leak check**, for ordinary keywords (decision 175).
   - It covers the product's ordinary campaigns, Sponsored Products and Sponsored Brands. It leaves out the rank
     campaigns, B2B and multi-product collections.
   - If they lost more than $10 over the last 7 settled days, the run pauses the ordinary keywords with 15+ clicks and
     no order in 90 days.
   - It never cuts other bids, never touches a rank campaign or a budget, and never holds back a new Prove-first campaign.
4. **Low stock** (decision 174).
   - At 14 days of stock or less, the run parks its increases "For human". That means new rank campaigns, raises, new SB
     videos, and budget or top-of-search increases.
   - Cuts, pauses and holds still go out.
   - A person releases the parked increases by approving them on the dashboard, or by clearing the product:
     `"stock_clearance": {"by": "<name>", "on": "<date>", "why": "<reason>"}` in its product file. A clearance lasts 7
     days. An agent never adds a clearance on its own.
5. **Day-1 check and read-back.**
   - Every written row is read back.
   - A spend jump of more than 1.5× on the first weekday after an apply opens an alert for the book owner.
   - Auto stays on (decision 163).

## 7. New searches, negatives and Sponsored Brands

- **Harvest:** Scale Insights imports search terms with 1+ order at or above the product's conversion gate. They go in as
  exact keywords into the product's harvest campaign ($5/day), at a starting bid worked out each run.
- **Negatives:** relevance negatives go through the negative audit's approval. The weekly run never adds "irrelevant"
  negatives on its own, and never negates an invest search or a close variant of one.
- **Sponsored Brands video:**
  - Every rank search gets one exact keyword in the AI's "Highest Converting Search Terms" video series, at its Sponsored
    Products invest bid.
  - Other SB keywords are priced at Sponsored Brands' own conversion (0.78 of Sponsored Products).
  - Amazon's SB minimum is $0.25.

## 8. Other product types

- **Seasonal products** follow their season's dates: wake, rank build, harvest, last mile, off. A seasonal product in
  season keeps breakeven bids. Its SQP adds last season's (decision 172).
- **Data stages:**
  - A launch-stage product (launched within 90 days, under 10 SQP queries) can't be planned yet.
  - An early-stage product has a few stricter rules.
  - Everything else is mature.
  - Old SQP is never a stop: plan on the newest there is (decision 172).
- **B2B and audiences:** Amazon Business campaigns and AMC audience campaigns have their own lanes and their own
  conversion. They are never treated as copies of the consumer campaigns (rulebook section 9).
- **Shared campaigns** (more than one ASIN) stay with Scale Insights. They're listed in the product file's
  `ownership_scope` (decision 172).
- **No AI product stays on Scale Insights rules** (decision 180, 2026-11-04). Its own ad groups come off the old
  Scale Insights strategies and rules onto the objectives made for AI bidding (101 to 144; exact owners on 103 and 144,
  with no blacklist), on 203 Optimum Hours (weekends on at −20%). Old schedules such as "Minimal 5-6am" are swapped for
  203 last: after the AI bids are written and read back, before Scale Insights' nightly run (about 02:10 SGT). Shared
  campaigns keep their setup.

## 9. When changes go live, and who decides

- **Apply as soon as the run finishes, at any hour and on any day** (decision 174).
  - The only wait is the switch hold: no writes in the 2 hours before a Scale Insights rule 203 ON switch, and none in
    the hour after it. `scripts/write_window.py check` enforces this.
  - Weekend bids at 80% of base (rule 203's −20%) are dayparting, not drift.
- **Auto rows go out without asking** (decisions 98, 114 and 116). Only rows parked "For human" wait for a person.
- **Sponsored Products and Sponsored Brands go out together** (decision 191, Nov 5). A run doesn't plan, so nothing
  goes out, until it has read the Sponsored Brands keywords, targets and themes and the SP ad groups. No run sends its
  SP bids and leaves the SB bids or ad-group default bids for another day.
- **Who decides:**
  - **Book owner:** every bid call on their products, adding a product to AI bidding, and clearing low stock.
  - **Lee:** revamping images, cutting a product, improving a listing.
  - **Kim:** price, taking a product off AI bidding, turning Auto back on, dayparting beyond the standard, and the
    rulebook.

## 10. Numbers the run reads for itself

- **Referral fee:** read from the last 14 days of settled orders (10+ units). Scale Insights' 0.15 means 15%; the bug
  that read it as 0.15% was fixed on 2026-10-31.
- **Profit per unit:** follows the settled fee. A price change is priced in straight away (decision 168).
- **Where the reports come from** (decision 186): Scale Insights by default (SQP, search terms, keywords, targets). When its
  usage allowance runs out, SoldScope for SQP and MarketplaceAdPros for the ad reports; the numbers match.
- **Overnight test copies** (`ON80 |`, `ON50 |`): the run leaves them alone; the test's own thread sets their bids.
