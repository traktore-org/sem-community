---
name: Module audit
about: Systematic audit of a stale SEM module (v1.7.1 stabilization program)
title: 'audit(<module>): <one-line summary>'
labels: ['audit']
assignees: []
---

> Follow [`docs/AUDIT_PLAYBOOK.md`](../../docs/AUDIT_PLAYBOOK.md) for the full
> workflow. The umbrella tracking issue is the parent of this audit — please
> link it here once known.

## Module

`<path/to/module.py>`

## Stats (from `docs/AUDIT_BACKLOG.md`)

- **Last touched**: YYYY-MM-DD
- **LOC**: N
- **Branches**: N
- **Decision-branch density**: 0.0NN
- **Backlog score**: N.NN

## Step 1 — PROD telemetry (captured YYYY-MM-DD)

<!-- Paste raw output from /api/states, .storage inspection, or
     ~/bin/validate-sem.sh. Real timestamps, no paraphrase. -->

```
<paste here>
```

Branch-hit distribution:

| Branch / state | Frequency | Notes |
|----------------|-----------|-------|
| ...            | ...       | ...   |

## Step 2 — Structural findings

<!-- For each finding: file:line + what it could do silently wrong.
     Cross-check against docs/adr/ — many "findings" are an existing
     ADR being ignored. -->

1. **<short title>** — `path:line` — <2-3 sentences on what could go wrong silently>
2. ...

## Step 3 — Telemetry-first proposal (no behavior change)

Sensor attribute additions on `sensor.sem_<name>` (mirror
`classifier_path` / `dampening_path`):

- `<module>_path` — enum string per decision branch
- `<intermediate_value_1>` — float, the input that drove the branch
- ...

Storage record additions (if persisting state):

- `<field_name>: Optional[<type>] = None` on the dataclass
- `restore_state` tolerates absent keys → loads as `None`

Schema-version bump? **<yes/no>** (only if config-entry shape changes)

## Step 6 — Algorithmic improvements (ranked, post-soak)

<!-- Filled in AFTER the telemetry beta has soaked 2-4 weeks. Use
     ruflo-goals:deep-researcher to rank candidates. Cite published
     sources. -->

1. **<change>** — leverage estimate, complexity (lines of code), source citation
2. ...

## Gate chain

- [ ] Local syntax (`python3.12 -c "import ast; ..."`)
- [ ] Focused test (`pytest tests/test_<N>_<module>_telemetry.py -q`)
- [ ] Full suite (`pytest custom_components/solar_energy_management/tests/ -q`)
- [ ] Reviewer (`ruflo-core:reviewer` over diff)
- [ ] HA-TEST deploy (`~/bin/deploy-test.sh --code-only`)
- [ ] Live attribute check (`curl /api/states/sensor.sem_<name>`)
- [ ] Push to `develop`, CI green
- [ ] **DO NOT TAG** — wait for explicit "tag it" from user

## Close conditions

- [ ] Telemetry surface in production
- [ ] At least one algorithmic improvement shipped OR conclusion documented as "current behavior is correct"
- [ ] Umbrella checkbox ticked

## Related

- Umbrella: #
- Playbook: [`docs/AUDIT_PLAYBOOK.md`](../../docs/AUDIT_PLAYBOOK.md)
- Precedents: #359 (classifier_path), #416 (dampening_path)
