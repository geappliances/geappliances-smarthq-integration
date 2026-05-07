# SmartHQ Integration — 작업 인수인계 (2026-05-07)

> **목적**: 새 대화창에서 이 파일을 읽어 이전 작업 컨텍스트를 즉시 파악하기 위한 핸드오버 문서.

---

## 1. 프로젝트 목표

SmartHQ HA Custom Integration을 **serviceType 기반 아키텍처**로 완전 재작성.

### 핵심 원칙
- `deviceType` 하드코딩 **없음**
- `coordinator.data[device_id]["item"]["services"]`의 `serviceType`만으로 entity 자동 생성
- 새 device 추가 시 integration **reload** 만으로 자동 매핑
- `make_unique_id(device_id, service_id, suffix)` → `{device_id}_{service_id}_{suffix}` 형식

### 참조 문서
- https://docs.smarthq.com/data-model/overview/
- https://docs.smarthq.com/data-model/common/services/

---

## 2. 환경 정보

| 항목 | 값 |
|---|---|
| Repository | `geappliances/geappliances-smarthq-integration` (Public) |
| Branch | `main` |
| HEAD commit | `a73c07d` |
| HA 로컬 경로 | `/root/homeassistant/custom_components/smarthq/` |
| Git 레포 경로 | `/root/homeassistant/geappliances-smarthq-integration/` |
| HA 환경 | Home Assistant OS on Raspberry Pi 4 (HA 2026.3.4) |
| Git 계정 | `Jaby-Firstbuild <jaebong.lee@geappliances.com>` (글로벌 설정 완료) |

### 유용한 명령어
```bash
# HA Core 재시작
ha core restart

# git 작업 (레포 경로에서 진행)
cd /root/homeassistant/geappliances-smarthq-integration
echo "계정: $(git config user.name) <$(git config user.email)>"
git add -A && git commit -m "..." && git push origin main
```

---

## 3. 커밋 히스토리 (최신순)

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

## 4. HACS 배포 현황

### 완료된 작업 ✅
| 항목 | 상태 | 비고 |
|---|---|---|
| 레포 구조 (`custom_components/smarthq/`) | ✅ | `5382fcf` |
| `hacs.json` 정리 | ✅ | `render_readme: true`, `filename` 제거 |
| `brands/icon.png`, `brands/logo.png` | ✅ | 레포 루트 `brands/` 디렉토리 |
| `LICENSE` (BSD 3-Clause) | ✅ | `a73c07d` |
| `README.md` My HA 설치 버튼 | ✅ | `d9694f5` |
| GitHub Release `v1.0.0` | ✅ | 발행 완료 |
| 레포 Public 전환 | ✅ | 완료 |
| HACS Custom Repository 등록 | ✅ | `geappliances/geappliances-smarthq-integration` |
| Git 계정 설정 | ✅ | `Jaby-Firstbuild <jaebong.lee@geappliances.com>` |

### 남은 작업 ⬜
| 항목 | 상태 | 비고 |
|---|---|---|
| HACS에서 Download 후 동작 검증 | ⬜ | 다음 세션에서 진행 |
| GitHub 레포 Description/Topics 설정 | ⬜ | About ⚙️ 권한 필요 |
| HACS Default Store 제출 | ⬜ | Custom repo 검증 후 진행 |

### HACS Download 검증 절차 (다음 세션)
```bash
# 1. 로컬 소스 백업
cp -r /root/homeassistant/custom_components/smarthq /root/homeassistant/custom_components/smarthq_backup

# 2. 로컬 소스 삭제
rm -rf /root/homeassistant/custom_components/smarthq

# 3. HA 재시작
ha core restart

# 4. HACS → SmartHQ → Download → HA 재시작
# 5. Settings → Devices & Services → SmartHQ 통합 추가
# 6. 정상 동작 확인 후 백업 삭제
rm -rf /root/homeassistant/custom_components/smarthq_backup
```

### HA brands PR 관련 (완료 처리)
- `home-assistant/brands` PR 제출했으나 **자동 Close** 됨
- 사유: HA 2026.3.0부터 custom integration은 레포 내 `icon.png`를 직접 사용
- **현재 `custom_components/smarthq/icon.png` (256×256) 이미 포함됨 → 별도 조치 불필요** ✅

---

## 5. 핵심 파일 구조

```
service_registry.py   — 모든 서비스/커맨드 상수 + make_unique_id() + 헬퍼
coordinator.py        — 1회 full fetch (update_interval=None), services[] 포함
ws_client.py          — WS 실시간 업데이트 → store (상태 갱신)
__init__.py           — bootstrap: coordinator → store → ws → platforms
                        PLATFORMS = ["sensor","number","switch","binary_sensor",
                                     "select","button","climate","water_heater",
                                     "light","text"]
switch.py             — toggle / mode(switch domain) / laundry.toggle.v2
select.py             — mode / cooking.mode.v1 / coffeebrewer / laundry.mode.v1
                        / dishwasher.mode.v1 / dishdrawer.mode.legacy
                        / dishwasher.custom.cycle / dishwasher.favorites.v1
                        / flexdispense / stainremoval / remotecycleselection
sensor.py             — 46개 elif 블록 (temperature/integer/cycletimer/double/
                        string/battery/cooking.state/laundry/dishwasher/dryer/
                        coffee/espresso/meter/scale/environmental/firmware 등)
number.py             — temperature(쓰기) / integer(쓰기) / dishdrawer.mode.legacy
button.py             — trigger / firmware / coffeebrewer / cooking.state /
                        dishdrawer / dishwasher.state.v1 / mixer.v1
binary_sensor.py      — 21개 elif 블록 (door/filter/firmware/dishwasher/
                        dishdrawer/cooking/demandresponse/pizzaoven/
                        enhancedfeature/stopwatch 등)
climate.py            — thermostat.v1 → SmartHQThermostatClimate
light.py              — color → SmartHQColorLight
                        cooking.prorange.accent.light → SmartHQAccentLight
text.py               — string(R/W) → SmartHQStringTextEntity
water_heater.py       — waterheater.v1 → SmartHQWaterHeater
```

### 데이터 흐름
```
HA 시작
  └─ coordinator.async_config_entry_first_refresh()
       └─ API: GET /v2/device/{id} → coordinator.data[device_id]["item"]["services"]
  └─ 각 platform async_setup_entry()
       └─ services[]를 serviceType별로 스캔 → entity 생성
  └─ ws_client 연결
       └─ WS 이벤트 → store[device_id]["snapshot"]["services"][service_id] 갱신
       └─ SIGNAL_DEVICE_UPDATED 발행 → entity.async_write_ha_state()
```

> **중요**: WS 스냅샷의 `services`는 `{ service_id: { state_fields } }` 형태
> (serviceType 키 없음). entity에서 snapshot 조회 시 service_id로 직접 접근해야 함.

---

## 6. 구현 현황 (74/87 ✅)

| # | serviceType | 플랫폼 | 상태 |
|---|---|---|---|
| 1 | `assistant` | — | ❌ 스킵 |
| 2 | `autoreorder` | — | ❌ 스킵 |
| 3 | `battery` | sensor | ✅ |
| 4 | `brew.mode.v1` | sensor + button | ✅ |
| 5 | `coffeebrewer.v1` | button + select | ✅ |
| 6 | `coffeebrewer.v2` | button + select | ✅ |
| 7 | `color` | light | ✅ |
| 8 | `connect.v1` | binary_sensor | ✅ |
| 9 | `cooking.advantium` | sensor + binary_sensor + button | ✅ |
| 10 | `cooking.burner.status.v1` | sensor | ✅ |
| 11 | `cooking.history` | — | ❌ 스킵 |
| 12 | `cooking.mode.multistage` | — | ❌ 복잡 |
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
| 55 | `matter.v1` | — | ❌ 스킵 |
| 56 | `meter` | sensor | ✅ |
| 57 | `mixer.v1` | sensor + button | ✅ |
| 58 | `mode` | select + switch | ✅ |
| 59 | `outdoorunit.info` | sensor | ✅ |
| 60 | `oven.flextimer` | sensor | ✅ |
| 61 | `oven.menutree` | sensor | ✅ |
| 62 | `photovoltaicpanel` | — | ❌ 스킵 |
| 63 | `pizzaoven.reminders` | binary_sensor | ✅ |
| 64 | `pizzaoven.state` | sensor + binary_sensor | ✅ |
| 65 | `power.usage` | sensor | ✅ |
| 66 | `pricingstructure` | — | ❌ 복잡 |
| 67 | `provider` | — | ❌ 스킵 |
| 68 | `remotecycleselection` | binary_sensor + select | ✅ |
| 69 | `scale.v1` | sensor | ✅ |
| 70 | `smartdispense` | sensor | ✅ |
| 71 | `sourdoughstarter.v1` | sensor | ✅ |
| 72 | `stainremoval` | select | ✅ |
| 73 | `stopwatch` | sensor + binary_sensor | ✅ |
| 74 | `string` | sensor(R/O) + text(R/W) | ✅ |
| 75 | `temperature` | sensor + number | ✅ |
| 76 | `thermostat.v1` | climate | ✅ |
| 77 | `timeintervals.v1` | — | ❌ 복잡 |
| 78 | `timeofday.v1` | — | ❌ 복잡 |
| 79 | `timeofuse.v1` | — | ❌ 복잡 |
| 80 | `toggle` | switch | ✅ |
| 81 | `trigger` | button | ✅ |
| 82 | `video.stream` | — | ❌ 스킵 |
| 83 | `volume.liquid.v1` | sensor | ✅ |
| 84 | `washer.config.cycle.v1` | sensor | ✅ |
| 85 | `washer.mycycle` | sensor | ✅ |
| 86 | `water.energy.estimates` | — | ❌ 스킵 |
| 87 | `waterheater.v1` | water_heater | ✅ |

**미구현 13개**
- 🔴 스킵 권장 (9개): `assistant`, `autoreorder`, `cooking.history`, `matter.v1`, `photovoltaicpanel`, `provider`, `video.stream`, `water.energy.estimates`, `pricingstructure`
- 🟡 복잡 (4개): `cooking.mode.multistage`, `timeintervals.v1`, `timeofday.v1`, `timeofuse.v1`

---

## 7. 버그 수정 이력

### fix: Smoker Cavity Light 엔티티 중복 생성 (`switch.py`, `a53e282`)
- **원인**: `mode` + `cloud.smarthq.domain.brightness` 서비스가 `serviceDeviceType`이
  다른 2개의 인스턴스로 등록됨 → `SmartHQModeSwitch` 2개 생성
- **수정**: `async_setup_entry`에 `seen_switch_domains: set[tuple]` 추가,
  동일 `(serviceType, domainType)` 쌍 중복 skip

### fix: Smoker Cook Mode unavailable 문제 (`select.py`, `d30a56e`)
- **원인**: `SmartHQCookingModeSelect.available`이 WS 스냅샷에서 `serviceType` 키로
  조회 → WS 스냅샷은 `service_id` 키 구조라 항상 miss → 기기 OFF 시 `return False`
- **수정**: `available`을 `return bool(self._cooking_svcs)`로 단순화.
  기기 ON/OFF 무관 항상 활성화

---

## 8. 알려진 구조적 주의사항

1. **WS 스냅샷 키 구조**: `snap["services"]`는 `{ service_id: {state_fields} }` 형태.
   `serviceType` 키 없음. snapshot 조회 시 반드시 `self._service_id`로 직접 접근.

2. **중복 서비스 인스턴스**: Smoker 등 일부 기기는 동일 serviceType+domainType 서비스가
   serviceDeviceType만 다르게 2개 등록됨. platform setup 시 dedup 처리 필요.

3. **cooking.mode.v1 / laundry.mode.v1 집계**: 기기당 여러 domain 서비스를
   하나의 select로 aggregation. `cooking_mode_svcs`, `laundry_mode_svcs` 리스트로
   수집 후 루프 밖에서 1개 엔티티 생성.

---

## 9. 실제 보유 기기 (테스트 환경)

| 기기 | Model | 비고 |
|---|---|---|
| Coffee Brewer | C7CGAAS00000 | — |
| Dryer | UNKNOWNMODEL01 | — |
| Smoker | P9SBAAS6VBB | Cavity Light 중복 수정 완료, Cook Mode 항상 활성화 |
| Toaster Oven | P9OIAAS6TBB | — |

---

## 10. 다음 세션 시작 방법

새 대화창에서:
1. 이 파일 첨부 또는 경로 언급: `/root/homeassistant/custom_components/smarthq/docs/HANDOVER.md`
2. 원하는 작업 요청

### 즉시 해야 할 우선순위 작업

1. **HACS Download 검증** (최우선)
   - 로컬 소스 백업 → 삭제 → HA 재시작
   - HACS → SmartHQ → Download → HA 재시작
   - SmartHQ 통합 추가 → 기기 정상 동작 확인
   - 검증 절차는 섹션 4 참조

2. **GitHub 레포 Description/Topics 설정**
   - `https://github.com/geappliances/geappliances-smarthq-integration` → About ⚙️
   - Description: `Home Assistant custom integration for GE Appliances SmartHQ connected devices`
   - Topics: `home-assistant`, `hacs`, `hacs-integration`, `smarthq`, `ge-appliances`

3. **HACS Default Store 제출** (Custom repo 검증 완료 후)
   - `https://github.com/hacs/default` Fork
   - `integration` 파일에 `geappliances/geappliances-smarthq-integration` 추가
   - PR 제목: `Add SmartHQ integration`
