# Amazon Negative Keyword Audit (a Claude skill)

A skill that teaches Claude to run a careful weekly negative-keyword audit on Amazon Sponsored
Products and Sponsored Brands ads. It:

- finds search terms that cost money and never sell, across every product in one run;
- protects terms that do sell (from the ad reports and from Search Query Performance), so it
  doesn't block real demand;
- flags negatives that are already live but too broad (like `the` or the product's own name);
- puts everything in an approval sheet, and changes nothing until you approve it.

## What you need

- **Claude** with the **MarketplaceAdPros** connector (for Amazon Ads data and changes).
- Optional: the **Scale Insights** connector and web app (blacklist and Search Query Performance),
  **Google Drive** (approval sheets), **Slack** (a recap after each run).

The skill asks for your own account details on its first run. Nothing about anyone else's account
is in this repo.

---

## How to install

Pick the one that matches how you use Claude.

### A. Claude app or claude.ai (website, desktop app)

1. On this page, click the file **`amazon-negative-keyword-audit.zip`** in the file list above,
   then click the **download button** (the arrow pointing down, top right of the file view).
   Don't unzip it.
2. Open Claude (the app or https://claude.ai).
3. Click your **name or initials** at the bottom left, then **Settings**.
4. Click **Capabilities** (on some versions it is called **Skills**).
5. Make sure **Code execution and file creation** is switched on.
6. Find **Skills** and click **Upload skill** (or **+ Add**, then **Upload a skill**).
7. Choose the zip file you downloaded (usually in your **Downloads** folder).
8. Make sure the new skill's switch is **on**.

### B. Claude Code (the terminal app)

1. Open Claude Code the way you normally do (type `claude` in your terminal and press Enter).
2. In the Claude Code chat box, type this and press Enter:
   ```
   /plugin marketplace add kevansoh1-source/amazon-negative-keyword-audit
   ```
3. Then type this and press Enter:
   ```
   /plugin install amazon-negative-keyword-audit@amazon-ppc-skills
   ```
4. Close Claude Code and open it again.

---

## How to use it

In a new chat, type something like:

> Run a negative keyword audit for ASIN B0XXXXXXXX

or, for many products at once:

> Run a negative keyword audit for these ASINs: B0XXXXXXXX, B0YYYYYYYY, B0ZZZZZZZZ

On the first run Claude asks a few setup questions (which tools you use, where approval sheets
go). It then shows you the proposed negatives in a sheet. **Delete the rows you don't want**;
the rows you leave are what gets applied. Nothing changes on Amazon before that.

## What's inside

| File | What it does |
|---|---|
| `skills/amazon-negative-keyword-audit/SKILL.md` | The audit method Claude follows |
| `skills/amazon-negative-keyword-audit/references/connectors.md` | Exact queries and tool calls |
| `skills/amazon-negative-keyword-audit/scripts/negkw-local.js` | Helper that de-duplicates terms and builds the word table (Node.js) |
| `skills/amazon-negative-keyword-audit/data/fingerprints.example.json` | Template for the product notes the skill keeps |
| `amazon-negative-keyword-audit.zip` | The same skill, packed for upload to the Claude app |

## Updating

- **Claude app:** download the new zip and upload it again (remove the old skill first).
- **Claude Code:** type `/plugin marketplace update amazon-ppc-skills`, then restart Claude Code.
