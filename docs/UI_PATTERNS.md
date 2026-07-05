# SEM UI Patterns

The design language for SEM dashboard cards. **The EV charger card is the
reference pattern** — when a new control surface is needed, it should look
like the EV charger already solved it. This guide exists so consistency is
the starting point, not the result of review rounds. (#565)

## The reference vocabulary

Taken from the EV card's *Charge Target* block, reused by the device goal
panel — copy these, don't reinvent:

### Settings panel (`charge-target-group` / `goal-editor`)
- Inset panel: 1px `--divider-color` border, radius 10px, background
  `rgba(255,255,255,0.025)`.
- **Uppercase section title** (11px, letter-spacing 0.05em, secondary color)
  with a small colored icon (e.g. `mdi:target` in `#8DC892`).
- **Unit / scope picker top-right** in the title row (small select, e.g.
  SOC ↔ kWh on the EV card, min ↔ kWh on the goal panel).

### Rows
- One setting per row: **label left, control right** (`display:flex`,
  control in a right-aligned cell), 1px separators between rows
  (`rgba(255,255,255,0.06)`), min-height ~32px.
- Time values get a small clock icon in `#5BC8D8`.

### The dual-handle range slider
- Green **At least** handle (`#8DC892`) = the guaranteed minimum/target.
- Orange **Up to** handle (`#ff9800`) = the ceiling/cap.
- Labels above the track: `At least <b green>X</b> … Up to <b orange>Y</b>`.
- The max handle parked at the far right means **no limit** — display
  `Full` (EV) or `∞` (goals), store the sentinel (100% / 0).
- Track: 6px, radius 3, fill = green→orange gradient; 18px white handles
  with 3px colored borders.
- **Value order: the big/primary value comes FIRST (left), secondary chips
  after** — on mobile the block wraps and the order must survive.

### Mode pickers
- **One mode picker per device/feature** — a single ladder where each step
  adds capability (EV: charge modes; devices: Off → Peak only → Surplus —
  solar only → + cheap top-up → + finish by deadline). Never two selects
  that both read as "mode".
- If the UI merges several backend fields into one picker, decompose in the
  card (`control_mode` + `top_up_policy`) — keep the backend API stable.
- Select chrome: custom caret SVG, radius 8px, 12px bold text, secondary
  background (copy `.ct-mode-select`).

### Help
- Cards with options get a **`?` toggle** that reveals inline help texts per
  option (not hover tooltips — they don't exist on touch).
- Every option's help explains behavior, not the label.

### Heroes / KPIs
- One hero per surface. Big value (orange for solar), small uppercase label
  beneath, live secondary values as pill chips beside it.
- **Never show the same number twice on one screen** — if a header and a
  card would both show it, the header wins and the card goes.

## Colors

Use the canonical palette (see project notes): solar `#ff9800`, grid import
`#488fc2`, export `#8353d1`, battery charge `#f06292` / discharge `#4db6ac`,
home `#5BC8D8`, EV `#8DC892`. Green/orange on sliders = guaranteed/ceiling.

## Process: mockup first

Visual work is proposed as a **mockup or annotated screenshot next to the
reference pattern before any implementation** — one approval, one build.

## Card checklist (every new/changed card)

- [ ] All strings via `semLocalize` keys, translated ×15 in
      `dashboard/translations.json`, `sem-localize.js` regenerated
- [ ] No backtick characters inside lit `html`/`css` template bodies
      (guarded by `tests/test_card_template_lint.py` — they blank the card)
- [ ] `watchedEntities` covers every entity the card reads
- [ ] `npm run build` — `dist/sem-cards.js` is what ships; `src/` alone does
      nothing
- [ ] Template uses the `*glass_card` anchor (defined at the first styled
      card of the Home view — check ordering when inserting cards)
- [ ] Translation parity + card lint tests green
