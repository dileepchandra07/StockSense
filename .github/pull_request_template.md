## What changed

<!-- One paragraph. What does this PR do, and why? -->

## Module

<!-- Tick the module(s) this touches. -->

- [ ] `catalog`
- [ ] `network`
- [ ] `ledger`
- [ ] `levels`
- [ ] `reorder`
- [ ] `valuation`
- [ ] `dashboard`
- [ ] `api`
- [ ] `docs` / `repo`

## How I verified it

<!--
Be specific. "Ran the test suite" is not enough — say what you ran and what you saw.
Paste the command and the relevant output.
-->

```
$ cd reference && python3 -m unittest -v
```

## Invariants

<!--
From docs/domain-model.md. Confirm this change does not break any of them.
If it does, explain why that is correct and update the doc.
-->

- [ ] Stock levels remain fully derived from the movement ledger
- [ ] Transfers conserve total quantity
- [ ] No path can drive internal stock negative
- [ ] Every move carries a reference for traceability
- [ ] `spec/openapi.yaml` still matches the implementation

## Screenshots or output

<!-- For anything user-visible. Delete this section if not applicable. -->

## Anything the reviewer should be suspicious of

<!--
Optional but encouraged. Known gaps, shortcuts taken, things you are unsure about,
follow-up work you deliberately deferred. Honesty here saves review cycles.
-->
