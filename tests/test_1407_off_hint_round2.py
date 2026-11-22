"""#1407 round 2 — the 0.9 kW one-phase screenshot, and the Off hint.

@RVallen78 on v2.3.0-beta.24: "1 phase" was right, but the card still said
"charging · 0 A" at 0.9 kW on one phase. The beta.24 card cannot draw that:
"1 phase" comes from the Zaptec's own phase currents, and the same reading
gives the amps (about 4 A). "0 A" beside it is the old card, which showed
SEM's own command (0 A while SEM is Off) — the phone app still ran the
bundle it had loaded before the update. The first test pins the backend
half of that state.

The same screenshot read "No charge. Contactor open. No charge." under the
mode, while evcc charged the car. Since #898 Off sends nothing: entering Off
stops the charge once, and from then on SEM leaves the charger alone. The
hint still said what Off did before #898 (class 191: a screen says what SEM
asks, not what happens).
"""
from __future__ import annotations

import json
import os

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
)

from .test_1407_charger_phase_currents import (  # noqa: F401 — fixture
    _rig,
    _zaptec_registry,
    registry,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: What every language said before: "No charge. Contactor open." / "No charge."
OLD_OFF_HINTS = {
    "cs": ("Bez nabíjení. Stykač otevřen.", "Bez nabíjení."),
    "da": ("Ingen opladning. Kontaktor åben.", "Ingen opladning."),
    "de": ("Kein Laden. Schütz offen.", "Kein Laden."),
    "en": ("No charge. Contactor open.", "No charge."),
    "es": ("Sin carga. Contactor abierto.", "Sin carga."),
    "fi": ("Ei latausta. Kontaktori auki.", "Ei latausta."),
    "fr": ("Pas de charge. Contacteur ouvert.", "Pas de charge."),
    "hu": ("Nincs töltés. Kontaktor nyitva.", "Nincs töltés."),
    "it": ("Nessuna carica. Contattore aperto.", "Nessuna carica."),
    "nl": ("Geen lading. Schakelaar open.", "Geen lading."),
    "no": ("Ingen lading. Kontaktor åpen.", "Ingen lading."),
    "pl": ("Brak ładowania. Stycznik otwarty.", "Brak ładowania."),
    "pt": ("Sem carga. Contactor aberto.", "Sem carga."),
    "ro": ("Fără încărcare. Contactor deschis.", "Fără încărcare."),
    "sv": ("Ingen laddning. Kontaktor öppen.", "Ingen laddning."),
    "zh": ("不充电。接触器断开。", "不充电。"),
}

KEYS = ("charge_mode_hint_off_surplus", "charge_mode_hint_off_overnight")


def _tables():
    with open(os.path.join(ROOT, "dashboard", "translations.json"),
              encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.asyncio
async def test_the_screenshot_one_phase_at_0_9_kw(registry):
    """SEM Off, evcc charges 3.9 A on one phase (0.9 kW): about 4 A and
    1 phase — the amps the beta.24 card shows beside "1 phase"."""
    _zaptec_registry(registry)
    rig = _rig("off", (3.9, 0.04, 0.02), 900)
    res = await rig.tick()
    assert res["charger_zap_commanded_current"] == 0
    assert res["charger_zap_measured_current"] == 3.9
    assert res["charger_zap_active_phases"] == 1


class TestTheOffHint:

    def test_every_language_is_listed(self):
        assert set(OLD_OFF_HINTS) == set(_tables())

    def test_english_says_what_off_does(self):
        en = _tables()["en"]
        assert en[KEYS[0]] == ("Choosing Off stops a running charge once. "
                               "Then SEM sends nothing.")
        assert en[KEYS[1]] == "Another system can still start a charge."

    @pytest.mark.parametrize("lang", sorted(OLD_OFF_HINTS))
    def test_no_language_still_says_no_charge(self, lang):
        block = _tables()[lang]
        new = tuple(block[k] for k in KEYS)
        assert all(new), f"{lang}: an Off hint is empty"
        for old, now in zip(OLD_OFF_HINTS[lang], new, strict=True):
            assert old not in now, f"{lang}: still says {old!r}"
        if lang != "en":
            en = _tables()["en"]
            assert new != tuple(en[k] for k in KEYS), f"{lang}: English"

    def test_the_hint_is_what_the_reconciler_does(self):
        """Off stops the charge once; then nothing, while another system
        charges — the two sentences of the hint, in the code."""
        rec = ChargerReconciler(charger_id="zap", heartbeat_s=5.0,
                                idle_disable_threshold=4)

        def obs(charging, power):
            return ObservedState(charging=charging, setpoint_a=0,
                                 self_charging=False, power_w=power,
                                 connected=True)

        rec.reconcile(DesiredState.IDLE, 0, obs(True, 1700.0), now=0.0)
        first = rec.reconcile(DesiredState.RELEASED, 0, obs(True, 1700.0),
                              now=10.0)
        assert [a.kind for a in first] == [ActionKind.DISABLE]
        rec.reconcile(DesiredState.RELEASED, 0, obs(False, 0.0), now=20.0)
        for i in range(6):   # evcc starts a charge after that
            later = rec.reconcile(DesiredState.RELEASED, 0, obs(True, 900.0),
                                  now=30.0 + i * 10)
            assert [a.kind for a in later] == [ActionKind.NONE]
