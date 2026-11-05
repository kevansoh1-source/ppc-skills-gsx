# Amazon PPC skills for Claude

Two skills that teach Claude to run Amazon Sponsored Products and Sponsored Brands ads the way a
real seller account runs them. Both change nothing on Amazon until a person has seen the plan.

| Skill | What it does |
|---|---|
| **Negative keyword audit** | Finds search terms that cost money and never sell, protects the ones that do, flags negatives that are too broad, and puts everything in an approval sheet. |
| **PPC AI bidding** | Runs one product's ads per run: bids each keyword from its own Search Query Performance conversion and breakeven, invests in rank on smaller searches with stop-loss checks, harvests new keywords, and handles Sponsored Brands video. It is the full system of a live account, so it is large; read its `SKILL.md` and `references/field-guide.md` to see how it works. |

## What you need

- **Claude** with the **MarketplaceAdPros** connector (Amazon Ads data and changes).
- Optional: the **Scale Insights** connector and web app, **Google Drive**, **Slack**.
- The bidding skill's scripts need **Python 3** (Claude Code, or the Claude app with code execution on).

Nothing about anyone else's account is in this repo: product files, IDs and team details were
taken out, and names and ASINs in examples are placeholders.

---

## How to install

Pick the one that matches how you use Claude.

### A. Claude app or claude.ai (website, desktop app)

1. On this page, click the zip for the skill you want in the file list above:
   **`amazon-negative-keyword-audit.zip`** or **`amazon-ppc-ai-bidding.zip`**.
   Then click the **download button** (the arrow pointing down, top right of the file view).
   Don't unzip it.
2. Open Claude (the app or https://claude.ai).
3. Click your **name or initials** at the bottom left, then **Settings**.
4. Click **Capabilities** (on some versions it is called **Skills**).
5. Make sure **Code execution and file creation** is switched on.
6. Find **Skills** and click **Upload skill** (or **+ Add**, then **Upload a skill**).
7. Choose the zip file you downloaded (usually in your **Downloads** folder).
8. Make sure the new skill's switch is **on**.

Repeat for the second zip if you want both.

### B. Claude Code (the terminal app)

1. Open Claude Code the way you normally do (type `claude` in your terminal and press Enter).
2. In the Claude Code chat box, type this and press Enter:
   ```
   /plugin marketplace add kevansoh1-source/amazon-negative-keyword-audit
   ```
3. Then type one or both of these, pressing Enter after each:
   ```
   /plugin install amazon-negative-keyword-audit@amazon-ppc-skills
   /plugin install amazon-ppc-ai-bidding@amazon-ppc-skills
   ```
4. Close Claude Code and open it again.

---

## How to use them

In a new chat, type something like:

> Run a negative keyword audit for ASIN B0XXXXXXXX

> Run the PPC AI bidding audit for ASIN B0XXXXXXXX (preview only)

On the first run Claude asks for your account details. The negative audit shows its proposals in a
sheet: **delete the rows you don't want**, and the rows you leave are what gets applied. With the
bidding skill, say "preview only" until you have set up `config.json` with your own IDs and read
how it decides.

## What's inside

| Path | What it is |
|---|---|
| `plugins/amazon-negative-keyword-audit/skills/…` | The negative audit: method, queries, helper script |
| `plugins/amazon-ppc-ai-bidding/skills/…` | The bidding skill: method, rulebook, field guide, Python scripts and their tests |
| `amazon-negative-keyword-audit.zip`, `amazon-ppc-ai-bidding.zip` | The same skills, packed for upload to the Claude app |

## Updating

- **Claude app:** download the new zip and upload it again (remove the old skill first).
- **Claude Code:** type `/plugin marketplace update amazon-ppc-skills`, then restart Claude Code.
