# Demo video script

**Target: 5:45. Hard ceiling 6:00.** The brief says *functional flow only* —
so this is the application, doing the things the problem statement asks for.
No slides, no architecture diagram, no code on screen.

Read the narration out loud twice before recording. It is written to be spoken,
not read.

---

## Pre-flight

Do this immediately before every take. Skipping it is how you end up on camera
with numbers that do not match the script.

```bash
cd StockSense
python -m app.seed          # rebuilds the demo data — numbers below assume this
python run.py               # http://127.0.0.1:5000
```

| Setting | Value | Why |
| --- | --- | --- |
| Browser | Chrome, **1440 × 900**, zoom **100%** | The layout is designed for this width |
| Windows | One. No other tabs, no bookmarks bar | `Cmd+Shift+B` hides the bar |
| Notifications | Off. Slack, mail, everything | |
| Cursor | Visible, move it deliberately | A wandering cursor is unwatchable |
| Account | `admin@stocksense.dev` / `demo1234` | Signed out at the start — beat 1 needs it |

> If you are on a machine that is not IST, export `DISPLAY_TZ` to your zone
> before seeding. The seeded history is built in the configured timezone, so
> the times on screen will still look like a normal working day.

**Do not re-seed mid-recording.** Beats 2–6 mutate the data in a fixed order;
they only add up if you start from a clean seed and follow the order.

---

## Timing budget

| # | Beat | In | Out | Length |
| --- | --- | --- | --- | --- |
| 1 | Sign in and the dashboard | 0:00 | 0:50 | 0:50 |
| 2 | Receive stock — the out-of-stock list clears | 0:50 | 1:45 | 0:55 |
| 3 | The system refuses to over-draw | 1:45 | 2:30 | 0:45 |
| 4 | Move stock inside the company | 2:30 | 3:15 | 0:45 |
| 5 | Correct a miscount | 3:15 | 3:55 | 0:40 |
| 6 | Ship it — pick, pack, validate | 3:55 | 4:30 | 0:35 |
| 7 | The ledger | 4:30 | 5:25 | 0:55 |
| 8 | Close | 5:25 | 5:45 | 0:20 |

---

## Beat 1 — Sign in and the dashboard `0:00 – 0:50`

**On screen.** Start at `http://127.0.0.1:5000`. It redirects to `/login`.

1. Type the email and password at normal speed. Do not paste.
2. Land on **Inventory Dashboard**.
3. Let it sit for two seconds, then move the cursor across the five KPI tiles,
   left to right.

**Say:**

> "StockSense is an inventory management system. Everything you are about to
> see is one screen away from this dashboard.
>
> These five numbers are what the problem statement asks for. Eleven products
> in stock, six that need attention, three receipts pending, two deliveries
> pending, three internal transfers scheduled.
>
> And this table underneath is every document in the system, filterable by
> type, status, warehouse, category — or searched by reference."

**Watch out.** The KPI tiles are read-only. Do not click them yet.

---

## Beat 2 — Receive stock `0:50 – 1:45`

*The clearest demonstration of the core idea: stock levels are not stored, they
are derived from the ledger. Validate a document and the levels move.*

**On screen.**

1. Scroll to **Out of stock** (bottom right). Four products. Read them:
   `CARTON-M`, `CHAIR-STK`, `DRIL-BIT-8`, `TAPE-50`.
2. Sidebar → **Receipts** → open **`WH/IN/00005`** (PackRight Industries).
3. Point at the workflow strip: **Draft → Awaiting goods → At the dock → Done**.
   It is currently *At the dock*. This is the delivery vocabulary the spec asks
   for, applied to a receipt.
4. Scroll to **Product lines**. Two lines: 500 cartons, 150 rolls of tape.
5. Click **Validate & apply to stock** (green, top right).
6. The page reloads with a green banner and a new card: *Ledger entries written
   by this document* — two rows.
7. Go back to the **Dashboard**. Out of stock is now **two** products.

**Say:**

> "A receipt is a plan. Nothing has touched stock yet — the document has been
> sitting at 'at the dock' since last week.
>
> Watch the out-of-stock list. Four products. Cartons and packing tape are on
> it, and here they are arriving.
>
> I validate. Two ledger entries are written — one per line, each with a
> reference, a timestamp and my name.
>
> Back on the dashboard, out of stock has dropped from four to two. I never
> typed a quantity into a stock field. I validated a document, and the level
> moved because the level is calculated from the ledger."

**Watch out.** Do not edit the lines. Validation is the point.

---

## Beat 3 — The system refuses to over-draw `1:45 – 2:30`

*This is the beat that lands. Most systems let you record an impossible
delivery and reconcile later. This one refuses.*

**On screen.**

1. **New delivery order** (top right of the dashboard).
2. Shipping warehouse **MAIN**, note *"Customer order SO-4491"*. Create it.
3. Add a line: **CHAIR-ERG**, quantity **20**. Add.
4. Add the same line again: **CHAIR-ERG**, quantity **20**. Add.
5. There are 28 chairs on hand. **Validate & apply to stock.**
6. A red banner appears:

   > **Not enough stock: CHAIR-ERG has 28 at MAIN/STOCK but the document needs 40**

7. Pause. Let the viewer read it. Then delete the document.

**Say:**

> "Two lines of twenty chairs. There are twenty-eight in the warehouse.
>
> Individually, neither line is a problem. Twenty is less than twenty-eight.
>
> But I validate the document, and it is refused. Not *'line two is too big'* —
> it says the document needs forty and there are twenty-eight. The check is
> per product, per location, across the whole document.
>
> That matters because the alternative is a system that happily records stock
> you do not have, and then a warehouse worker discovers it. This one will not
> let the ledger contain an impossible number."

**Watch out.** The message names the exact shortfall. Read it verbatim — do not
paraphrase.

---

## Beat 4 — Move stock inside the company `2:30 – 3:15`

*The spec's own example: rack to rack, warehouse to warehouse. The total does
not change. Only the location does.*

**On screen.**

1. Sidebar → **Internal Transfers** → open **`WH/INT/00003`** (MAIN → NORTH,
   staged, 80 sheets of `STL-SHT-2`).
2. Sidebar → **Products** → open **`STL-SHT-2`**. Point at the location
   breakdown: **300 at MAIN/STOCK**, nothing at NORTH.
3. Back to `WH/INT/00003` (**use the browser Back button** — the reference is
   in the URL).
4. **Validate & apply to stock.**
5. Back to the product page. Now: **220 at MAIN/STOCK, 80 at NORTH/STOCK**.

**Say:**

> "This transfer moves eighty steel sheets from the main warehouse to the
> northern depot.
>
> Before I touch it, look at where this product lives. Three hundred sheets,
> all in MAIN.
>
> I validate. And the same product page now reads two hundred and twenty in
> MAIN, eighty in NORTH.
>
> Three hundred either way. Nothing was created and nothing was destroyed —
> two ledger entries, one out and one in, and the total is conserved because
> it is computed from those entries rather than stored and adjusted."

**Watch out.** If the browser Back button skips the reload, navigate through the
sidebar instead. Never refresh with `Cmd+R` on a POST result page.

---

## Beat 5 — Correct a miscount `3:15 – 3:55`

*A miscount becomes a visible, attributed correction — not a silent overwrite.*

**On screen.**

1. Sidebar → **Adjustments** → open **`WH/ADJ/00003`** (cycle count, draft).
2. Point at the line: **counted 27**, at MAIN/STOCK.
3. Open **Products → CHAIR-ERG** in another tab and show **28 on hand**. Come
   back.
4. **Validate & apply to stock.**
5. The ledger card shows exactly **one** entry, quantity **1** — the difference.
6. Dashboard → **Recent ledger activity**. The newest row is the adjustment.

**Say:**

> "Someone counted twenty-seven chairs. The system thinks there are twenty-eight.
>
> The adjustment does not store the count. It stores the *difference*. I
> validate, and one ledger entry appears — a correction of one unit, with a
> reference, a reason and my name on it.
>
> That is deliberate. If this overwrote the number, the error would vanish and
> nobody could ever answer *who changed this, when, and why*. Here the mistake
> and the fix are both on the record, permanently."

---

## Beat 6 — Ship it: pick, pack, validate `3:55 – 4:30`

*Thirty-five seconds, and it closes the loop on the delivery vocabulary.*

**On screen.**

1. Sidebar → **Delivery Orders** → open **`WH/OUT/00004`** — status **Packed**.
2. Point at the strip: **Draft → Picked → Packed → Done**.
3. Point at the status buttons underneath: **Back to draft**, **Back to
   picked**. *"The buttons tell you which way you are moving."*
4. **Validate & apply to stock.** Status becomes **Done**. Stock leaves.

**Say:**

> "A delivery is picked, then packed, then validated — the three steps the
> problem statement names. Same five states as every other document, but the
> words are the ones a warehouse actually uses.
>
> These buttons move it backwards if the pick was wrong, and they say so.
>
> Validating ships it, and the chairs leave the ledger."

---

## Beat 7 — The ledger `4:30 – 5:25`

*Close on this. It is the thing that makes everything before it credible.*

**On screen.**

1. Sidebar → **Move History**. Twenty-three rows, newest first. *(Eighteen
   from the seed, plus the five entries beats 2–6 just wrote.)*
2. Scroll slowly through the top third. Point at one row — a receipt:
   product, quantity, `Supplier → MAIN/STOCK`, reference `WH/IN/00004`,
   the person's name.
3. Hover the **When** column to show the exact timestamp tooltip.
4. Apply a filter: **Warehouse → MAIN**. Then **Movement type → Delivery**.
   Show the list narrow to just those rows.

**Say:**

> "Every quantity in this system traces back to a row on this page. Every
> movement, in and out, with the document that caused it, the locations it
> moved between, the person who did it, and the second it happened.
>
> There is no editable stock number anywhere in StockSense. There is this
> ledger, and there are views that add it up. Which is why the two numbers
> that disagreed earlier — twenty-eight and forty — could be compared at all,
> and why every correction stays visible forever."

**Watch out.** Do not scroll to the bottom. Twenty-three rows is enough; the
point is density, not length.

---

## Beat 8 — Close `5:25 – 5:45`

**On screen.** Stay on Move History. Stop moving the mouse.

**Say:**

> "That is StockSense. Receipts, deliveries, transfers and adjustments, on one
> append-only ledger, with every level derived from it rather than stored.
>
> Built with Flask, SQLite and server-rendered templates. One command to run,
> no build step, and a hundred and eighty-six tests that pin the inventory
> rules — including the one that refuses to let stock go negative.
>
> The repository and the README are linked below."

**Stop recording.**

---

## If something breaks

Keep rolling, fix it, narrate the fix. A recovered stumble reads as competence;
a cut reads as a cover-up.

| Symptom | What to do | What to say |
| --- | --- | --- |
| Numbers do not match the script | You skipped the re-seed, or ran the beats out of order | "Let me reset the demo data" — re-seed, restart the take |
| Red error on a page you did not expect | Read it aloud, then delete the document you were building | "The system is refusing to record something impossible — which is the point" |
| Page looks wrong / CSS missing | `Cmd+Shift+R` | — |
| You lose your place | Sidebar → Dashboard, then continue | "Back on the dashboard" |
| A beat runs long | Cut beat 6 (pick/pack). Never cut beat 3 (the guard) | — |

**Never cut beat 3.** It is the only beat that shows the system making a
decision rather than recording one, and it is the strongest answer to *"what
happens when the data is wrong?"* in the Q&A round.

---

## Upload

| | |
| --- | --- |
| Length | 5:45 (ceiling 6:00) |
| Resolution | 1440 × 900 or larger; 1080p is fine |
| Audio | Voice-over. No music under narration |
| Access | **Anyone with the link** — check it in a private window before submitting |
| Where | The submission portal, alongside the repository link |

Verify the link from a browser you are not signed into. An "anyone in the
organisation" link is not an open link, and it is the most common way a video
submission fails silently.

---

## The three sentences to land

If the viewer remembers nothing else:

1. **Stock levels are not stored — they are calculated from an append-only
   ledger.** (Beat 2)
2. **The system refuses to record an impossible movement.** (Beat 3)
3. **Every number on screen traces back to a row with a time, a reference and
   a person.** (Beat 7)
