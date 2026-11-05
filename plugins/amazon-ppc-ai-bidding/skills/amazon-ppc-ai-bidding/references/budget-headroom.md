# Budget headroom: more budget for campaigns that run out at a profit (added 2026-10-20)

**Why.** Kim, 2026-10-20: "if it runs out of budget prematurely, we should look to increase our budget to maximize the
goodness of a low-ACOS campaign."
- **What the first check found** (logs/2026-10-20-budget-headroom-check.md):
  - Most campaigns that run out of budget are above breakeven, so the cap is limiting a loss.
  - The few that run out at a profit had budgets set by hand at $3–10/day, and nothing raised them.
  - Scale Insights' budget rule 10003 tops out at $10/day.
  - This skill only set budgets for its own invest campaigns.
- **Applied the same day by hand** (Kim's OK, MarketplaceAdPros change set 50e08b53, read back live):
  - 20 Assorted Birthday Cards 5x7 (B0SAMP0015), Broad: $3 → $10;
  - the same product, Phrase: $3 → $10;
  - gratitude cards B2B Phrase (B0SAMP0024): $10 → $20.
  - All three are in `data/budget_steps.json`.

## The rule

Every number lives in `config.json` → `budget_headroom`.

**Rank campaigns (since 2026-10-31, Kim, decision 174: "invest in validated keywords without a money cap").** The
product's Invest and Prove-first campaigns (validated searches) are judged without the ACOS condition: a rank campaign
out of budget on **5+ of the last 14 days** steps up **+50%** whatever its ACOS and orders, because losses are accepted for
ranking. It keeps the **$50/day** ceiling (and Amazon's suggestion when it suggests more than today), the step size and
the **7-day** wait before the next step. It is never stepped back on ACOS: the stop-loss is its brake. Once stepped, the
budget stays: the run's invest step reads the ledger (`data/budget_steps.json`) and keeps the stepped budget instead of
writing the $10 (Invest) or $5 (Prove first) standard again. When the same run also moves the campaign's top of search,
the step rides on that 'Budget and top of search' row (`budget_step_folded`), so the campaign gets one budget write, and
`log_invest.py` records it in the ledger all the same. The table below is for every other campaign.

| Verdict | When | Action |
|---|---|---|
| **Step up** | Out of budget (spend ≥ 90% of budget) on **5+ of the last 14 days**, **3+ orders**, ACOS **≤ 80% of the product's breakeven ACOS** | Budget **+50%**, rounded up to whole dollars, at least +$1. Never past Amazon's suggested budget (when it suggests more than today) or $50/day |
| **Step back** | A recorded step is a week old, and its campaign ran **above breakeven** on **20+ clicks** since the step | Back to the budget before the step |
| **Waiting** | A recorded step is under 7 days old | Nothing: no second step before the first is judged |
| **Watch** | Out of budget at a profit, but ACOS between 80% and 100% of breakeven, or under 3 orders | Nothing: more budget buys sales and rank, not profit |
| **At a loss** | Out of budget above breakeven | Nothing: the budget is limiting a loss (the bids are the lever) |

**How it's measured:**
- **Breakeven ACOS = unit profit ÷ price.** Each product has its own (13–53% across the catalog), never one number for the
  whole account. AI products take it from the product file; the catalog scan takes Scale Insights `BreakEvenAcosPercent`.
- **ACOS and orders leave out the newest 2 days,** because 14-day attribution is still filling them. Capped days count all 14.
- **The live budget** (`campaigns.json`) beats the report's.
- **Consumer invest campaigns are judged as rank campaigns** since 2026-10-31 (above). Until then they were left out,
  their budget always the invest step's (`budgets` in config). A B2B campaign holding a business invest this run (a
  Business invest, a business new exact keyword, or an owner already invested as planned) still takes its budget from that
  invest (rulebook 9.5). **Every other B2B campaign is judged like a consumer one.** Audience campaigns are left as they are until phase 2. The catalog scan
  doesn't know shopper kinds, so it lists every campaign.

## Who says yes

- **Lane.** Every 'Budget step' row is Auto since autonomous runs (2026-10-22, decision 98; lanes.AUTO_TYPES): the run
  applies it itself. Until then it was `human`.
- **Approval level** (sweep-playbook; rulebook 7.10): every step, up or back and whatever its size, is the **book
  owner's** (Kim, 2026-10-22, decision 95). Until then a step up worth more than $50 a month (budget change × 30) was
  Lee's.
- **Payload.** It goes out budget-only, in `5_campaign_updates.json`: `{"type": "sp_campaigns", "campaignId": "…",
  "budget": {"budget": 15, "budgetType": "DAILY"}}`. No `dynamicBidding`, so placements and bidding strategy stay as live.
- **Recording.** After the apply, `log_invest.py` writes each step that went out (applied_rows.json) to
  `data/budget_steps.json`. Next week's plan judges it from there.

## In the weekly run (AI-managed products)

1. **Pull** (weekly-run step 3). Save the product's campaign days as `<run>/campaign_days.json`, or as
   `campaign_days_p2.json` … pages. MAP `run_report_sql`, the 15 days to yesterday, `limit` 1000:

   ```sql
   SELECT campaignId AS campaign_id, any_value(campaignName) AS campaign, date, SUM(cost) AS cost,
          MAX(campaignBudgetAmount) AS budget, SUM(sales14d) AS sales, SUM(purchases14d) AS orders, SUM(clicks) AS clicks
   FROM sponsored_products_campaigns
   WHERE date BETWEEN DATE '<today-15>' AND DATE '<today-1>' AND campaignName LIKE '%<ASIN>%'
   GROUP BY campaignId, date
   ORDER BY campaignId, date
   LIMIT 1000 OFFSET <0, 1000, ...>
   ```

   Page with OFFSET until a page returns fewer than 1,000 rows. Save each result as MAP returns it (`{"data": [...]}`).
2. **Plan.** `plan.py` adds the 'Budget step' rows (step 62 on the preview). The plan summary's `budget_headroom` lists:
   - steps waiting for their week;
   - watch and capped-at-a-loss counts;
   - `need_budget_recs`: step-up campaigns with no Amazon suggestion yet.
3. **Optional: Amazon's suggestion.** For the campaigns in `need_budget_recs`, call MAP
   `get_amazon_ads_campaigns_budget_recs`, save it as `<run>/budget_recs.json` and plan again. The step is then capped at
   Amazon's suggested budget, and its row shows the share of time in budget.
4. **Without `campaign_days.json`** the run proposes no steps and says so in the summary. That is never an error. The
   weekly leak check (rulebook 2g, decision 175) reads the same rows, so it doesn't run either.

## The catalog scan (everything else: monthly machine check)

The Scale Insights catalog isn't AI-managed, so nothing here writes to Amazon. The scan writes a report and a payload for
the team to approve and apply.

1. **Pull the campaign days** for the whole account with the same SQL, without the `LIKE` filter. To keep the pages few,
   keep only:
   - the campaigns that could qualify (out of budget on 5+ days, 3+ orders);
   - every campaign in `data/budget_steps.json` (a step is judged even when its campaign no longer runs out).

   On 2026-10-20 that was 102 campaigns: 1,437 rows, two pages.

   ```sql
   WITH d AS (SELECT campaignId, any_value(campaignName) AS campaignName, date, SUM(cost) AS cost,
                     MAX(campaignBudgetAmount) AS budget, SUM(sales14d) AS sales, SUM(purchases14d) AS orders, SUM(clicks) AS clicks
              FROM sponsored_products_campaigns
              WHERE date BETWEEN DATE '<today-15>' AND DATE '<today-1>' GROUP BY campaignId, date),
   c AS (SELECT campaignId FROM d GROUP BY campaignId
         HAVING COUNT(*) FILTER (WHERE budget > 0 AND cost >= 0.9 * budget) >= 5 AND SUM(orders) >= 3)
   SELECT campaignId AS campaign_id, campaignName AS campaign, date, cost, budget, sales, orders, clicks FROM d
   WHERE campaignId IN (SELECT campaignId FROM c) OR campaignId IN (<the ledger's campaign ids>)
   ORDER BY campaignId, date LIMIT 1000 OFFSET <0, 1000, ...>
   ```

2. **Breakeven ACOS.** Run Scale Insights `get_product_metadata` (50 ASINs a call) for the ASINs in the campaign names.
   Save `{ASIN: BreakEvenAcosPercent}` as `be.json`.
3. **Run the scan:**

   ```
   python scripts/budget_headroom.py catalog --days days_p1.json days_p2.json ... --be be.json [--recs recs.json] --today <day> --out <dir>
   ```

   - It leaves out AI-managed products; their weekly run has them. `--include-ai` lists them too.
   - It writes `budget_headroom.md` (the report), `budget_headroom.json`, `budget_steps_payload.json` (MAP rows for the
     step-ups and step-backs) and `need_budget_recs.json`.
   - Fetch Amazon's suggestions for the campaigns `need_budget_recs.json` lists, then run it again with `--recs`.
4. **Approve, apply, record.** A person approves the steps. Apply the payload through MAP during the audit and read the
   budgets back. Then record each step:

   ```
   python scripts/budget_headroom.py record --campaign-id <id> --campaign "<name>" --asin <ASIN> --from 3 --to 5 --date <day> --by "<name>" --why "<one line>" --ref "<change set>"
   ```

## Limits

- **Sponsored Products only.** On Oct 20 no Sponsored Brands campaign ran out of budget below its product's breakeven.
  SB attribution is brand-wide, which makes per-product ACOS loose.
- **It judges the campaign as a whole,** not hours. With rule 203 a campaign that runs out by midday loses its afternoon,
  and that is exactly the case this targets.
- **A step buys the hours after the old cap.** They usually convert worse, so expect the next step's ACOS to drift up.
  The step-back is the guard.
