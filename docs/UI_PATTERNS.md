# SEM UI patterns

The SEM dashboard looks and behaves like Home Assistant itself. A user who
knows HA should not see a second design. When a screen needs something, use
HA's element and HA's theme variables first; draw our own only when HA has
none. (#565, #1321)

## Surfaces

- One real `ha-card` per section (`_sec()` in `base/sem-next-base.js`). The
  card gives radius, border, background and shadow from the theme:
  `--ha-card-border-radius`, `--ha-card-border-width`, `--ha-card-border-color`,
  `--ha-card-box-shadow`, `--card-background-color`.
- No own shadow, border colour, radius, blur or glass. Lines inside a card
  are `--divider-color`. A tile inside a card uses `--secondary-background-color`.
- 16 px padding in a card, 16 px between cards, 12 px between rows' content.

## Colours

- Only theme variables. A hex or rgba literal is allowed only as the fallback
  inside `var(--x, #fallback)`. `test/next-theme-lint.test.js` fails the
  build on any other.
- Text: `--primary-text-color`, `--secondary-text-color`. Accent:
  `--primary-color`. States: `--success-color`, `--warning-color`,
  `--error-color`. Icons: `--state-icon-color`.
- Energy: `--energy-solar-color`, `--energy-grid-consumption-color`,
  `--energy-grid-return-color`, `--energy-battery-in-color`,
  `--energy-battery-out-color`. Home and car have no HA variable:
  `--sem-home-color`, `--sem-ev-color`. Fallbacks are the SEM palette: solar
  `#ff9800`, grid import `#488fc2`, export `#8353d1`, battery in `#f06292`,
  battery out `#4db6ac`, home `#5bc8d8`, car `#8dc892`. Use `NEXT_COLORS` in
  code, never the hex.
- Text on a coloured bar: `--sem-on-energy` (dark) or `--sem-on-energy-dark`
  (light).
- Check every new colour in a light and a dark theme.

## Type

- Inherit HA's font. Never set a font family (code: `--code-font-family`).
- Sizes `--ha-font-size-s/m/l/xl` (12, 14, 16, 20 px), weights
  `--ha-font-weight-normal/medium/bold`, always with a fallback.
- Card heading: sentence case, 16 px, weight 500. Secondary text 14 px or 12 px
  in `--secondary-text-color`. No uppercase, no letter spacing.
- No own title bar: HA's toolbar names the dashboard. The header row holds
  only small pills (battery, price, live or observing) and the All settings
  switch.

## Controls

Each helper draws HA's element when it is defined and a native one in HA's
look when it is not. HA loads many elements late, so never assume one.
`ensureHaElements()` (`util/ha-elements.js`) asks HA's card helpers to load
them, waits with a timeout and the card renders again.

| Need | Helper | HA element | Fallback |
|---|---|---|---|
| On or off | `_switch()` | `ha-switch` | switch button |
| Pick one of a few | `_seg()` | `ha-control-select`, `ha-button-toggle-group` | button group |
| Button | `_btn()` | `ha-button` | `.btn` |
| Text, number, time | `_input()` | `ha-textfield` | `input` |
| Pick from a list | `_select()` | `ha-selector` | `select` |
| Pick an entity | `ha-entity-picker` | itself | text box with a datalist |
| Dialog | `ha-dialog` | itself | fixed overlay |
| Message | `_toast()` | `hass-notification` (HA's snackbar) | message in the card |

- Tapping a value that is an entity opens HA's more-info (`_moreInfo()`).
  Never an own popup for an entity.
- Show friendly names. An entity id appears only in more-info.
- A selector's menu takes focus: give it no blur handler, close with Cancel.

## Rows, sentences, folds

- A row: icon, label left, value right, a divider above (`_row()`).
- **Settings rows**: a setting is a Home Assistant settings row (`_setRow()`):
  the label left in plain words, the value right (numbers through the locale
  helper, with the unit), one line of help under the label. Tap the row, or
  press Enter or Space, and `_editDialog()` opens with the control for the
  kind: `ha-selector` for a choice, `ha-textfield` for a number, text or time,
  `ha-entity-picker` for an entity; the styled native field when HA has not
  loaded the element. A boolean is a switch on the row, no dialog. A group
  keeps one short read-only sentence above its rows. System rows are built
  from `groups()` in `util/next-settings.js` (the one source), so a new
  setting needs a slot there and a label key, never its own markup. Changes
  wait in the Apply bar; Devices rows write at once, as before.
- **Everyday and All settings**: one switch in the header for every screen,
  read with `getAllSettings()` and set with `setAllSettings()` (`util/view-mode.js`,
  kept per browser). Everyday keeps open what is used daily; the rest sits in
  folds. A warning that needs action is never folded. Folding must never make
  a setting unreachable.
- Help text explains what an option does, not its label. No hover-only hints.
- One number once per screen. If the header shows it, the card does not.
- One mode picker per device. If the UI merges backend fields, decompose in
  the card and keep the backend API stable.

## Process

Visual work starts as a mockup next to the reference. One approval, one
build.

## Card checklist

- [ ] Strings via `semLocalize` keys, all 16 languages in
      `dashboard/translations.json`, `scripts/regenerate_localize.py` run
- [ ] No backtick inside a lit `html` or `css` template, comments included
      (`tests/test_card_template_lint.py`)
- [ ] `_watchIds()` lists every entity the card reads
- [ ] `npm run build`: `dist/sem-cards.js` is what ships
- [ ] `npm test` green, including the theme lint
- [ ] Looked at in a light and a dark theme
