# SmartHQ Integration — Handover Document (2026-05-07)

> **Purpose**: Read this file at the start of a new session to immediately restore the previous work context.

---

## 1. Project Goals

Complete rewrite of the SmartHQ HA Custom Integration to a **serviceType-based architecture**.

### Core Principles
- No `deviceType` hardcoding
- Entities auto-generated solely from `serviceType` in `coordinator.data[device_id]["item"]["services"]`
- Adding a new device only requires an integration **reload** for automatic mapping
- `make_unique_id(device_id, service_id, suffix)` → `{device_id}_{service_id}_{suffix}` format

### Reference Docs
- https://docs.smarthq.com/data-model/overview/
- https://docs.smarthq.com/data-model/common/services/

---

## 2. Environment

| Item | Value |
|---|---|
| Repository | `geappliances/geappliances-smarthq-integration` (Public) |
| Branch | `main` |
| HEAD commit | `a73c07d` |
| HA local path | `/root/homeassistant/custom_components/smarthq/` |
| Git repo path | `/root/homeassistant/geappliances-smarthq-integration/` |
| HA environment | Home Assistant OS on Raspberry Pi 4 (HA 2026.3.4) |
| Git account | `Jaby-Firstbuild <jaebong.lee@geappliances.com>` (globally configured) |

### Useful Commands
```bash
# Restart HA Core
ha core restart

# Git operations (run from repo path)
cd /root/homeassistant/geappliances-smarthq-integration
echo "Account: $(git config user.name) <$(git config user.email)>"
git add -A && git commit -m "..." && git push origin main
```

---

## 3. Commit History (latest first)

```
a73c07d  chore: add BSD 3-Clause License
d9694f5  docs: add HACS My HA install button to README
d304a51  chore: update hacs.json — remove filename field, add render_readme
5382fcf  refactor: move integration files into custom_components/smarthq/ for HACS compliance
ad90b14  chore: add brand assets directory at repo root for HACS
7185d4f  feat(smoker): replace Smoke Level number with select entity (0–5)
a87e56c  fix(smoker): disable diagnostic-only entities by default
d2ee157  feat(smoker): rename Warm → Keep Warm / Auto Warm → Keep Warm Time/Temperature
```

---

## 4. HACS Deployment Status

### Completed ✅
| Item | Status | Notes |
|---|---|---|
| Repo structure (`custom_components/smarthq/`) | ✅ | `5382fcf` |
| `hacs.json` cleanup | ✅ | `render_readme: true`, removed `filename` |
| `brands/icon.png`, `brands/logo.png` | ✅ | `brands/` directory at repo root |
| `LICENSE` (BSD 3-Clause) | ✅ | `a73c07d` |
| `README.md` My HA install button | ✅ | `d9694f5` |
| GitHub Release `v1.0.0` | ✅ | Published |
| Repository set to Public | ✅ | Done |
| HACS Custom Repository registered | ✅ | `geappliances/geappliances-smarthq-integration` |
| Git account configured | ✅ | `Jaby-Firstbuild <jaebong.lee@geappliances.com>` |

### Remaining ⬜
| Item | Status | Notes |
|---|---|---|
| Verify Download via HACS | ⬜ | Next session |
| Set GitHub repo Description/Topics | ⬜ | Requires About ⚙️ access |
| Submit to HACS Default Store | ⬜ | After custom repo verified |

### HACS Download Verification Steps (next session)
```bash
# 1. Backup local source
cp -r /root/homeassistant/custom_components/smarthq /root/homeassistant/custom_components/smarthq_backup

# 2. Remove local source
rm -rf /root/homeassistant/custom_components/smarthq

# 3. Restart HA
ha core restart

# 4. HACS → SmartHQ → Download → Restart HA
# 5. Settings → Devices & Services → Add SmartHQ integration
# 6. Confirm normal operation, then remove backup
rm -rf /root/homeassistant/custom_components/smarthq_backup
```

### HA brands PR (resolved)
- PR submitted to `home-assistant/brands` but **auto-closed**
- Reason: Since HA 2026.3.0, custom integrations use `icon.png` directly from the repo
- **`custom_components/smarthq/icon.png` (256×256) already included — no further action needed** ✅

---

## 5. Key File Structure

```
service_registry.py   — All service/command constants + make_unique_id() + helpers
coordinator.py        — Single full fetch (update_interval=None), includes services[]
ws_client.py          — WS real-time updates → store (state refresh)
__init__.py           — Bootstrap: coordinator → store → ws → platforms
                        PLATFORMS = ["sensor","number","switch","binary_sensor",
                                     "select","button","climate","water_heater",
                                     "light","text"]
switch.py             — toggle / mode(switch domain) / laundry.toggle.v2
select.py             — mode / cooking.mode.v1 / coffeebrewer / laundry.mode.v1
                        / dishwasher.mode.v1 / dishdrawer.mode.legacy
                        / dishwasher.custom.cycle / dishwasher.favorites.v1
                        / flexdispense / stainremoval / remotecycleselection
sensor.py             — 46 elif blocks (temperature/integer/cycletimer/double/
                        string/battery/cooking.state/laundry/dishwasher/dryer/
                        coffee/espresso/meter/scale/environmental/firmware, etc.)
number.py             — temperature(write) / integer(write) / dishdrawer.mode.legacy
button.py             — trigger / firmware / coffeebrewer / cooking.state /
                        dishdrawer / dishwasher.state.v1 / mixer.v1
binary_sensor.py      — 21 elif blocks (door/filter/firmware/dishwasher/
                        dishdrawer/cooking/demandresponse/pizzaoven/
                        enhancedfeature/stopwatch, etc.)
climate.py            — thermostat.v1 → SmartHQThermostatClimate
light.py              — color → SmartHQColorLight
                        cooking.prorange.accent.light → SmartHQAccentLight
text.py               — string(R/W) → SmartHQStringTextEntity
water_heater.py       — waterheater.v1 → SmartHQWaterHeater
```

### Data Flow
```
HA start
  └─ coordinator.async_config_entry_first_refresh()
       └─ API: GET /v2/device/{id} → coordinator.data[device_id]["item"]["services"]
  └─ Per-platform async_setup_entry()
       └─ Scan services[] by serviceType → create entities
  └─ ws_client connected
       └─ WS event → update store[device_id]["snapshot"]["services"][service_id]
       └─ Publish SIGNAL_DEVICE_UPDATED → entity.async_write_ha_state()
```

> **Important**: `services` in the WS snapshot is `{ service_id: { state_fields } }`.
> There is no `serviceType` key. Always access snapshot using `self._service_id` directly.

---

## 6. Implementation Status (74/87 ✅)

| # | serviceType | Platform | Status |
|---|---|---|---|
| 1 | `assistant` | — | ❌ Skipped |
| 2 | `autoreorder` | — | ❌ Skipped |
| 3 | `battery` | sensor | ✅ |
| 4 | `brew.mode.v1` | sensor + button | ✅ |
| 5 | `coffeebrewer.v1` | button + select | ✅ |
| 6 | `coffeebrewer.v2` | button + select | ✅ |
| 7 | `color` | light | ✅ |
| 8 | `connect.v1` | binary_sensor | ✅ |
| 9 | `cooking.advantium` | sensor + binary_sensor + button | ✅ |
| 10 | `cooking.burner.status.v1` | sensor | ✅ |
| 11 | `cooking.history` | — | ❌ Skipped |
| 12 | `cooking.mode.multistage` | — | ❌ Complex |
| 13 | `cooking.mode.v1` | sensor + select + button | ✅ |
| 14 | `cooking.oven.probe.temperature` | sensor + binary_sensor | ✅ |
| 15 | `cooking.prorange.accent.light` | light | ✅ |
| 16 | `cooking.state.v1` | sensor + button | ✅ |
| 17 | `cooktop.closedloop` | sensor | ✅ |
| 18 | `cooktop.sousvide` | sensor | ✅ |
| 19 | `cycletimer` | sensor | ✅ |
| 20 | `delaywindow` | sensor | ✅ |
| 21 | `demandresponse.event.v1` | sensor + binary_sensor | ✅ |
| 22 | `demandresponse.state.v1` | sensor | ✅ |
| 23 | `descale.v1` | sensor + binary_sensor | ✅ |
| 24 | `dish.config.v1` | binary_sensor | ✅ |
| 25 | `dishdrawer.mode.legacy` | select(×2) + binary_sensor + number | ✅ |
| 26 | `dishdrawer.state.legacy` | sensor + binary_sensor + button | ✅ |
| 27 | `dishwasher.custom.cycle` | select + binary_sensor | ✅ |
| 28 | `dishwasher.favorites.v1` | select | ✅ |
| 29 | `dishwasher.mode.v1` | select | ✅ |
| 30 | `dishwasher.rinse.agent` | sensor | ✅ |
| 31 | `dishwasher.state` | binary_sensor | ✅ |
| 32 | `dishwasher.state.legacy` | sensor + binary_sensor | ✅ |
| 33 | `dishwasher.state.v1` | sensor + button | ✅ |
| 34 | `door` | binary_sensor | ✅ |
| 35 | `double` | sensor | ✅ |
| 36 | `dryer.config.cycle.v1` | sensor | ✅ |
| 37 | `dryer.mycycle` | sensor | ✅ |
| 38 | `dryer.rack` | binary_sensor | ✅ |
| 39 | `dryer.vent.health.mode` | sensor | ✅ |
| 40 | `enhancedfeature.v1` | binary_sensor | ✅ |
| 41 | `environmental.sensor` | sensor | ✅ |
| 42 | `espressomaker.v1` | sensor | ✅ |
| 43 | `filter.v1` | binary_sensor | ✅ |
| 44 | `firmware.v1` | sensor + binary_sensor + button | ✅ |
| 45 | `flexdispense` | select + binary_sensor | ✅ |
| 46 | `integer` | sensor + number | ✅ |
| 47 | `laundry.bulktank` | sensor | ✅ |
| 48 | `laundry.commercial.v1` | sensor | ✅ |
| 49 | `laundry.downloadablecycle` | sensor | ✅ |
| 50 | `laundry.mode.v1` | select | ✅ |
| 51 | `laundry.pethair` | sensor | ✅ |
| 52 | `laundry.pricemenu.v1` | sensor + binary_sensor | ✅ |
| 53 | `laundry.state.v1` | sensor | ✅ |
| 54 | `laundry.toggle.v2` | switch | ✅ |
| 55 | `matter.v1` | — | ❌ Skipped |
| 56 | `meter` | sensor | ✅ |
| 57 | `mixer.v1` | sensor + button | ✅ |
| 58 | `mode` | select + switch | ✅ |
| 59 | `outdoorunit.info` | sensor | ✅ |
| 60 | `oven.flextimer` | sensor | ✅ |
| 61 | `oven.menutree` | sensor | ✅ |
| 62 | `photovoltaicpanel` | — | ❌ Skipped |
| 63 | `pizzaoven.reminders` | binary_sensor | ✅ |
| 64 | `pizzaoven.state` | sensor + binary_sensor | ✅ |
| 65 | `power.usage` | sensor | ✅ |
| 66 | `pricingstructure` | — | ❌ Complex |
| 67 | `provider` | — | ❌ Skipped |
| 68 | `remotecycleselection` | binary_sensor + select | ✅ |
| 69 | `scale.v1` | sensor | ✅ |
| 70 | `smartdispense` | sensor | ✅ |
| 71 | `sourdoughstarter.v1` | sensor | ✅ |
| 72 | `stainremoval` | select | ✅ |
| 73 | `stopwatch` | sensor + binary_sensor | ✅ |
| 74 | `string` | sensor(R/O) + text(R/W) | ✅ |
| 75 | `temperature` | sensor + number | ✅ |
| 76 | `thermostat.v1` | climate | ✅ |
| 77 | `timeintervals.v1` | — | ❌ Complex |
| 78 | `timeofday.v1` | — | ❌ Complex |
| 79 | `timeofuse.v1` | — | ❌ Complex |
| 80 | `toggle` | switch | ✅ |
| 81 | `trigger` | button | ✅ |
| 82 | `video.stream` | — | ❌ Skipped |
| 83 | `volume.liquid.v1` | sensor | ✅ |
| 84 | `washer.config.cycle.v1` | sensor | ✅ |
| 85 | `washer.mycycle` | sensor | ✅ |
| 86 | `water.energy.estimates` | — | ❌ Skipped |
| 87 | `waterheater.v1` | water_heater | ✅ |

**13 not implemented**
- 🔴 Recommended to skip (9): `assistant`, `autoreorder`, `cooking.history`, `matter.v1`, `photovoltaicpanel`, `provider`, `video.stream`, `water.energy.estimates`, `pricingstructure`
- 🟡 Complex (4): `cooking.mode.multistage`, `timeintervals.v1`, `timeofday.v1`, `timeofuse.v1`

---

## 7. Bug Fix History

### fix: Smoker Cavity Light duplicate entity creation (`switch.py`, `a53e282`)
- **Cause**: The `mode` + `cloud.smarthq.domain.brightness` service was registered as two instances
  with different `serviceDeviceType` values → two `SmartHQModeSwitch` entities created
- **Fix**: Added `seen_switch_domains: set[tuple]` to `async_setup_entry`; duplicate
  `(serviceType, domainType)` pairs are now skipped

### fix: Smoker Cook Mode unavailable issue (`select.py`, `d30a56e`)
- **Cause**: `SmartHQCookingModeSelect.available` looked up the WS snapshot using `serviceType` key
  → WS snapshot uses `service_id` keys, so always a miss → returned `False` when device was off
- **Fix**: Simplified `available` to `return bool(self._cooking_svcs)`;
  always enabled regardless of device on/off state

---

## 8. Known Structural Notes

1. **WS snapshot key structure**: `snap["services"]` is `{ service_id: {state_fields} }`.
   No `serviceType` key. Always access snapshot using `self._service_id` directly.

2. **Duplicate service instances**: Some devices (e.g. Smoker) register the same serviceType+domainType
   service twice with different `serviceDeviceType` values. Deduplication is required during platform setup.

3. **cooking.mode.v1 / laundry.mode.v1 aggregation**: Multiple domain services per device are
   aggregated into a single select. Collected into `cooking_mode_svcs` / `laundry_mode_svcs` lists,
   then one entity is created outside the loop.

---

## 9. Devices Available for Testing

| Device | Model | Notes |
|---|---|---|
| Coffee Brewer | C7CGAAS00000 | — |
| Dryer | UNKNOWNMODEL01 | — |
| Smoker | P9SBAAS6VBB | Cavity Light dedup fixed, Cook Mode always enabled |
| Toaster Oven | P9OIAAS6TBB | — |

---

## 10. How to Start the Next Session

In a new chat:
1. Attach this file or reference its path: `/root/homeassistant/custom_components/smarthq/docs/HANDOVER.md`
2. State the desired task

### Prioritized Next Steps

1. **HACS Download Verification** (highest priority)
   - Backup local source → remove → restart HA
   - HACS → SmartHQ → Download → restart HA
   - Add SmartHQ integration → confirm devices work normally
   - See section 4 for detailed steps

2. **Set GitHub Repo Description/Topics**
   - `https://github.com/geappliances/geappliances-smarthq-integration` → About ⚙️
   - Description: `Home Assistant custom integration for GE Appliances SmartHQ connected devices`
   - Topics: `home-assistant`, `hacs`, `hacs-integration`, `smarthq`, `ge-appliances`

3. **Submit to HACS Default Store** (after custom repo verified)
   - Fork `https://github.com/hacs/default`
   - Add `geappliances/geappliances-smarthq-integration` to the `integration` file
   - PR title: `Add SmartHQ integration`
