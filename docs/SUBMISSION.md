# Submission checklist

Derived from the Odoo x LPU Jalandhar Hackathon 2026 participant email and the
Virtual Round guide. **Read the "Blockers" section first — two items are not
done and they are the ones that cost marks.**

Last verified against the live repository: 2026-09-26 15:30 IST.

---

## Requirements

### Team leader only

| # | Requirement | Status |
| --- | --- | --- |
| 1 | Select the problem statement in the portal (**cannot be changed afterwards**) | ❓ confirm — not verifiable from the repo |
| 2 | Add the evaluator as a collaborator on the GitHub repo | ❌ **unverified — see Blocker 2** |
| 3 | Submit the GitHub repository link under "Submit Problem Solution" | ❓ confirm — repo created 09:22 IST, before the 10:00 AM cut-off |
| 4 | After coding ends, submit the demo video link (open access, 5–6 min) | ⬜ pending |
| 5 | Confirm the green "Submission Successful" banner appears | ⬜ pending |

### Everyone

| # | Requirement | Status |
| --- | --- | --- |
| 6 | Repository is **public** (private counts as not submitted) | ✅ public, verified |
| 7 | Latest code is on `main` | ✅ `main` is the default branch and up to date |
| 8 | **Every member commits their own code** | ❌ **see Blocker 1** |
| 9 | Push at least once every hour | ⚠️ last push 15:01 IST — keep the cadence |
| 10 | Commit messages explain what was done | ✅ conventional commits in use |
| 11 | Join the Discord server | ❓ do this if not already done |
| 12 | Follow the timeline on the hackathon screen | ❓ check the event page |

---

## Blockers

### Blocker 1 — Three team members have zero commits

This is the serious one.

```
$ git shortlog -sne --all
     2  HARSHA VARDHAN KOMARA <komara.harsha2025@lpu.in>
```

Every commit in the repository is authored by one person. The other three
collaborators (`dileepchandra07`, `bit-odoo`, `kottanamanikanta1-dot`) have not
committed anything.

Two stated consequences, both bad:

> "Every team member is required to commit their own code. Individual commits will
> be used to identify each member's contribution accordingly. This will directly
> impact your team's final evaluation and results."

> "Questions are generated based on code personally committed by you, matching the
> GitHub account linked on your profile."
> "If a 'no questions could be prepared' error displays, ensure the repository is
> public and commits were pushed from your linked account."

So as things stand, three members will hit **"no questions could be prepared"** and
cannot participate in the Q&A round at all. That is a team-level loss, not just a
personal one.

**The fix has to be real work, not cosmetic commits.** Do not fabricate commits or
re-author existing ones — the Q&A will expose it immediately, because you will be
asked to explain code you did not write. Each member should build something
genuinely theirs and commit it themselves from their own linked account.

### Blocker 2 — Evaluator not confirmed as a collaborator

Current collaborators: `dileepchandra07` (admin), `Xranger-rootX`,
`kottanamanikanta1-dot`, `bit-odoo`.

Whether `bit-odoo` is the assigned evaluator or a teammate is not something I can
determine from the repository. **The team leader must confirm the evaluator's
GitHub handle from the event page's left panel and add them.** If they are not a
collaborator, the round cannot be evaluated.

---

## Suggested work split

Scoped so nobody touches the same files. Every item is real, demonstrable, and
explainable in a Q&A — which is the point.

### Member A — REST API from the existing contract

`spec/openapi.yaml` is a complete 13-operation contract that the application does
**not currently serve**. Implementing it is the single most valuable piece of
unclaimed work in the repository.

- **New files:** `app/api.py`, `tests/test_api.py`
- **Touch:** `app/__init__.py` (one blueprint registration)
- Start with the read endpoints: `GET /products`, `GET /stock`, `GET /moves`,
  `GET /stock/low`. Then `POST /moves`.
- The domain logic already exists in `app/engine.py` — this is a thin HTTP layer
  over functions that are already tested. Say so in the Q&A; it is the honest and
  correct answer.

### Member B — CSV export for reporting

Every list view currently ends at the screen. Exports are what an inventory
manager actually asks for next.

- **New files:** `app/views_reports.py`, `app/templates/reports/index.html`
- **Touch:** `app/__init__.py`, `app/templates/base.html` (one nav link)
- Export stock levels and move history as CSV, respecting the same filters the
  list pages already accept.
- Explain in the Q&A that the export reads the derived levels, so it can never
  disagree with the screen.

### Member C — Test coverage and seed realism

- **New files:** `tests/test_exports.py` or `tests/test_api.py` depending on what
  A and B build
- **Touch:** `app/seed.py` (more products, more movement history)
- Add a test that the exported CSV totals reconcile against `engine.on_hand()`.
- Expand the seed to ~40 products and a month of history so the dashboard looks
  lived-in during the demo.

### Demo video — whoever presents

5–6 minutes, **functional flow only**, open-access link. The six beats are already
written in [`roadmap.md`](roadmap.md#demo-script). Rehearse twice before recording.

---

## Before every push

```bash
python -m unittest discover -s tests    # 133 application tests
cd reference && python -m unittest      # 53 domain invariant tests
```

CI runs both on every push. Do not push red.

## Deadline-day order of operations

1. Each member commits their own work, from their own account.
2. Team leader confirms the evaluator is a collaborator.
3. Team leader confirms the problem statement and repo link are submitted.
4. Rehearse the demo. Record it.
5. Upload the video as an open-access link and submit it.
6. Confirm the green "Submission Successful" banner.

Do not leave steps 5 and 6 to the last ten minutes — the video upload is the step
most likely to fail on an unfamiliar connection.
