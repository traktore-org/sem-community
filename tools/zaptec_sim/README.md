# zaptec_sim — a faithful Zaptec stand-in for SEM testing

SEM supports Zaptec chargers and has no Zaptec hardware on either rig. #804
showed what that costs: three separate defects in the Zaptec path (English-only
entity matching, the wrong current entity, an installation-scoped service
fallback) all reached a reporter before anyone noticed, because nothing here
could exercise the brand.

This integration is that missing rig. It is modelled on the real thing rather
than on what would be convenient:

| modelled after | source |
|---|---|
| `unique_id = f"{object_id}_{key}"` | `custom-components/zaptec` `entity.py` |
| `charger_max_current` / `charger_min_current` on the CHARGER | its `number.py` |
| `available_current` / `three_to_one_phase_switch_current` on the INSTALLATION | its `number.py` |
| `has_entity_name = True` → entity_ids follow the DEVICE name | its `entity.py` |
| soft pause at current 0, auto-resume when raised | @coppe218's measured half-hour hold (#804) |
| hard stop needs an explicit resume | EVCC `CmdStopChargingFinal` / `CmdResumeCharging` |
| 1-phase = switch current 32 A, 3-phase = 0 A | EVCC `zaptec.go` (Go2 path) |

The domain is `zaptec_sim`, which SEM's detection matches through the same
tolerant `zaptec*` prefix rule that exists for HACS builds like
`zaptec_custom` — so discovery sees it exactly as it would see a real one.

**Device names default to Dutch and owner-prefixed** ("Guido Coppes Lader"),
reproducing the reporter's registry, because that localisation is precisely
what broke detection. Override with the `device_prefix` option to test other
languages.

## Services

- `zaptec_sim.plug_in` / `zaptec_sim.unplug` — cable state
- `zaptec_sim.hard_stop` — the latching stop; raising the current will NOT
  resume charging afterwards, only the resume button will
- `zaptec_sim.set_phases` — force the believed phase count

## NOT for production

A test fixture. It talks to nothing, and every value is local.
