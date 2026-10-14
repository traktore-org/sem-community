"""(#1083) Replay recorded days with other battery settings.

Pure model: no Home Assistant, no hass. ``hourly_day`` is the input,
``balance`` closes and prices an hour with SEM's own rules,
``battery_sim`` drives SEM's real battery decisions hour by hour and
``summary`` adds the days up. Every simulated number is an estimate.
"""
