# Contributing to StockSense

Four people are pushing to this repository. These conventions exist so we do not
spend the hackathon resolving merge conflicts and untangling each other's work.

---

## The one rule that matters

**Never commit directly to `main`.**

`main` is the demo-ready branch. At any moment it should be in a state you would
be comfortable showing to a judge. All work happens on a branch and arrives via
pull request.

## Branch naming

```
<type>/<short-slug>
```

| Type | Use for | Example |
| --- | --- | --- |
| `feat/` | New functionality | `feat/stock-move-ledger` |
| `fix/` | Bug fixes | `fix/transfer-conserves-quantity` |
| `docs/` | Documentation only | `docs/api-contract` |
| `refactor/` | Restructuring, no behaviour change | `refactor/extract-levels` |
| `chore/` | Tooling, dependencies, config | `chore/add-ci-workflow` |

Keep the slug short, lowercase, hyphen-separated. `feat/reorder-alerts` is good.
`feat/adding-the-new-reorder-alert-feature-for-warehouses` is not.

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/). This keeps
the history readable and gives us a changelog for the final pitch for free.

```
<type>(<scope>): <description>
```

```
feat(ledger): record transfers between warehouses
fix(levels): derive on-hand from moves instead of cached counter
docs(architecture): document stack options and trade-offs
test(reference): cover insufficient-stock guard on delivery
chore(repo): add MIT license and multi-stack gitignore
```

Rules:

- **Imperative mood** in the description — "add rule", not "added rule" or "adds rule".
- **Lowercase** after the colon. No trailing full stop.
- Scope is optional but encouraged; use the module name from the table below.
- One logical change per commit. If your message needs the word "and", split it.

Valid scopes: `catalog`, `network`, `ledger`, `levels`, `reorder`, `valuation`,
`dashboard`, `api`, `repo`, `docs`, `reference`.

## Pull requests

1. **Branch** off an up-to-date `main`.
2. **Push** and open a PR using the template.
3. **Fill in the template properly.** State what changed, how you verified it,
   and anything the reviewer should be suspicious of.
4. **Get one approval** from a teammate. Reviewers: read the diff, do not rubber-stamp.
5. **Squash merge.** One PR becomes one commit on `main`.

Keep PRs small. A 200-line PR gets a real review; a 2,000-line PR gets a shrug
and a merge. If a branch has grown past ~400 lines of diff, split it.

### Before you open a PR

```bash
git fetch origin
git rebase origin/main        # resolve conflicts on your branch, not in the PR
cd reference && python3 -m unittest -v
```

At minimum, make sure the reference test suite still passes. If you changed
domain behaviour, add a test for it — the invariants in
[`docs/domain-model.md`](docs/domain-model.md) are the contract we all rely on.

## Reviewing

You are responsible for what you approve. Two things to check every time:

- **Does it break an invariant?** If a change lets stock levels drift from the
  ledger, or lets a transfer create or destroy quantity, it is wrong regardless
  of how clean the code looks.
- **Does it match the API contract?** [`spec/openapi.yaml`](spec/openapi.yaml) is
  the interface the frontend and backend agree on. Changing it is fine — changing
  it silently is not.

Be direct in review comments. "This lets a delivery drive stock negative" is
useful. "Nit: maybe consider possibly…" is not.

## Repository conventions

- **Never commit secrets.** API keys, database passwords and tokens go in `.env`,
  which is gitignored. If you commit one by accident, say so immediately — do not
  quietly rewrite history.
- **Documentation lives in `docs/`.** Design decisions belong in
  [`docs/architecture.md`](docs/architecture.md) with the reasoning, not buried in
  a PR description nobody will read again.
- **The reference implementation is a reference.** `reference/` exists to pin down
  domain semantics in runnable form. It is not the product — do not grow it into one.

## Questions

If something here is unclear or wrong, fix it and open a `docs/` PR. A convention
nobody understands is worse than no convention.
