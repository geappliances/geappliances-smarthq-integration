# Service Mapping 기반 엔티티 생성 규칙

## 개요

SmartHQ 통합은 GE 가전기기 API로부터 수신한 서비스 목록을
**`SERVICE_MAPPING` Allowlist** 기반으로 Home Assistant 엔티티로 변환합니다.

### 핵심 원칙
- **Allowlist 방식**: `SERVICE_MAPPING`에 없는 serviceType은 자동 차단 (노출 안 함)
- **두 종류의 mapping**: `standard` (공통 핸들러) / `custom` (기기 전용 클래스)
- **기기 종류 무관**: serviceType → mapping → entity 생성으로 완전 통일

---

## 엔티티 생성 흐름

```
API 서비스 (serviceType)
        │
        ▼
  SERVICE_MAPPING에 있는가?
        │
   YES  │  NO
        │   └─→ 무시 (노출 안 함)
        ▼
  플랫폼별 async_setup_entry
   1. Coordinator 준비 확인
   2. 기기·services[] 순회
   3. Allowlist 체크
   4. 현재 플랫폼 대상 여부 확인
   5. domainType / supportedCommands 조건 분기
        ▼
  HA 엔티티 생성
```

---

## Mapping 타입

| 타입 | 설명 |
|------|------|
| `standard` | 공통 핸들러 재사용. 기기 종류 무관하게 동일 로직 |
| `custom` | 기기 전용 클래스. 복잡한 상태·명령 로직 포함 |
| *(미등록)* | 자동 차단 — `factory_reset`, `firmware`, `assistant` 등 |

---

## 전체 SERVICE_MAPPING 현황

### Standard Mappings

#### Switch
| serviceType | 플랫폼 |
|---|---|
| `toggle` | switch (domainType에 따라 lock/light로 분기) |
| `laundry.toggle.v2` | switch |

#### Binary Sensor
| serviceType | 플랫폼 | device_class |
|---|---|---|
| `door` | binary_sensor | door |
| `filter.v1` | binary_sensor | problem |
| `connect.v1` | binary_sensor | connectivity |
| `enhancedfeature` | binary_sensor | — |
| `dryer.rack` | binary_sensor | — |

#### Sensor / 읽기 전용
| serviceType | 플랫폼 | 비고 |
|---|---|---|
| `temperature` | sensor + **select** | CMD_TEMPERATURE_SET 있으면 select도 생성 |
| `integer` | sensor + **number** | 쓰기 가능이면 number도 생성 |
| `double` | sensor | — |
| `string` | sensor + **text** | 쓰기 가능이면 text도 생성 |
| `meter` | sensor | energy/voltage/water 등 |
| `battery` | sensor | — |
| `cycletimer` | sensor | — |
| `stopwatch` | sensor + binary_sensor | 실행 중 여부 binary도 생성 |
| `environmental.sensor` | sensor | 공기질 센서 |
| `delaywindow` | sensor | DR 창 읽기 전용 |
| `powerusage` | sensor | — |
| `volume.liquid` | sensor | — |
| `scale` | sensor | — |
| `outdoorunit.info` | sensor | — |
| `smartdispense` | sensor | — |
| `dryer.venthealth.mode` | sensor | — |
| `laundry.bulktank` | sensor | — |
| `laundry.pethair` | sensor | — |
| `dishwasher.rinseagent` | sensor | — |
| `cooktop.closedloop` | sensor | — |
| `cooktop.sousvide` | sensor | — |
| `dryer.config.cycle.v1` | sensor | — |
| `dryer.mycycle` | sensor | — |
| `washer.config.cycle.v1` | sensor | — |
| `washer.mycycle` | sensor | — |
| `demandresponse.state.v1` | sensor | — |
| `oven.menutree` | sensor | — |
| `laundry.commercial.v1` | sensor | — |
| `laundry.downloadablecycle` | sensor | — |
| `espressomaker.v1` | sensor | — |
| `sourdoughstarter.v1` | sensor | — |

#### Select
| serviceType | 플랫폼 | 비고 |
|---|---|---|
| `mode` | select + switch | domainType에 따라 분기 (아래 참고) |
| `stainremoval` | select | — |
| `flexdispense` | select + binary_sensor | — |

#### Button
| serviceType | 플랫폼 |
|---|---|
| `trigger` | button |

---

### Custom Mappings (기기 전용 클래스)

| serviceType | 플랫폼 | 핸들러 |
|---|---|---|
| `cooking.mode.v1` | sensor + select + button + number | `SmartHQCookingMode` |
| `cooking.state.v1` | sensor + button | `SmartHQCookingState` |
| `cooking.oven.probe.temp` | sensor + binary_sensor | `SmartHQCookingOvenProbeTemp` |
| `cooking.burner.status` | sensor | `SmartHQCookingBurnerStatus` |
| `cooking.advantium` | sensor + binary_sensor + button | `SmartHQCookingAdventium` |
| `brew.mode` | sensor + button | `SmartHQBrewMode` |
| `coffeebrewer.v1` | button + select + binary_sensor | `SmartHQCoffeeBrewerV1` |
| `coffeebrewer.v2` | button + select + binary_sensor | `SmartHQCoffeeBrewerV2` |
| `laundry.state` | sensor | `SmartHQLaundryState` |
| `laundry.mode.v1` | select | `SmartHQLaundryMode` |
| `laundry.pricemenu.v1` | sensor + binary_sensor | `SmartHQLaundryPriceMenu` |
| `dishwasher.state.v1` | sensor + button | `SmartHQDishwasherStateV1` |
| `dishwasher.state` | binary_sensor | `SmartHQDishwasherState` |
| `dishwasher.mode.v1` | select | `SmartHQDishwasherModeV1` |
| `dishwasher.custom.cycle` | select + binary_sensor | `SmartHQDishwasherCustomCycle` |
| `dishwasher.favorites.v1` | select | `SmartHQDishwasherFavoritesV1` |
| `descale.v1` | sensor + binary_sensor | `SmartHQDescaleV1` |
| `dish.config.v1` | binary_sensor | `SmartHQDishConfigV1` |
| `dishdrawer.mode.legacy` | select + binary_sensor + number | `SmartHQDishDrawerModeLegacy` |
| `dishdrawer.state.legacy` | sensor + binary_sensor + button | `SmartHQDishDrawerStateLegacy` |
| `dishwasher.state.legacy` | sensor + binary_sensor | `SmartHQDishwasherStateLegacy` |
| `remotecycleselection` | binary_sensor + select | `SmartHQRemoteCycleSelection` |
| `demandresponse.event.v1` | sensor + binary_sensor | `SmartHQDemandResponseEvent` |
| `pizzaoven.state` | sensor + binary_sensor | `SmartHQPizzaOvenState` |
| `pizzaoven.reminders` | binary_sensor | `SmartHQPizzaOvenReminders` |
| `mixer.v1` | sensor + button | `SmartHQMixer` |
| `oven.flextimer` | sensor | `SmartHQOvenFlexTimer` |
| `color` | light | `SmartHQColorLight` |
| `cooking.prorange.accent.light` | light | `SmartHQAccentLight` |
| `thermostat.v1` | climate | `SmartHQThermostatClimate` |
| `waterheater.v1` | water_heater | `SmartHQWaterHeater` |

---

## domainType 기반 세부 분기 규칙

같은 `serviceType`이라도 `domainType`에 따라 생성 결과가 달라집니다.

### `mode` 서비스

```
mode 서비스
    ├─ SWITCH_MODE_DOMAINS          → switch
    │     lock, override, brightness, light
    │
    ├─ READONLY_MODE_DOMAINS        → 생성 안 함 (읽기 전용 무시)
    │     icemaker
    │     demandresponse  ← 전력회사 자동 제어, 사용자 조작 불가
    │
    └─ 그 외                        → select (다중 옵션)
```

### `temperature` 서비스

```
temperature 서비스
    ├─ CMD_TEMPERATURE_SET 없음     → sensor (읽기 전용)
    └─ CMD_TEMPERATURE_SET 있음     → select
          stepped 정수 목록 (API min/max 범위)
          예) 냉장실 34~42°F, 냉동실 -6~5°F, 온수기 90~185°F
```

### `toggle` 서비스

```
toggle 서비스
    ├─ LOCK_DOMAINS                 → switch (device_class: lock)
    ├─ BRIGHTNESS_DOMAINS           → light
    └─ 그 외                        → switch (일반)
```

---

## 명시적 차단 목록

| serviceType | 차단 이유 |
|---|---|
| `firmware.v1` | 펌웨어 업데이트 — 민감 작업, HA 엔티티로 노출 금지 |
| `factory_reset` | 공장 초기화 — 안전상 차단 |
| `assistant` | 내부 서비스 |
| `autoreorder` | 내부 서비스 |
| 기타 미등록 | 신규 API 서비스는 검토 후 등록 전까지 자동 차단 |

---

## 구현 완료 현황

| 단계 | 내용 | 상태 |
|------|------|------|
| Phase 1 | `SERVICE_MAPPING` Registry 설계 | ✅ |
| Phase 2 | `switch.py` 파일럿 적용 | ✅ |
| Phase 3 | `binary_sensor.py` 적용 | ✅ |
| Phase 4 | `sensor`, `select`, `button`, `number` 등 전체 적용 | ✅ |
| Phase 5 | 데이터 기반 dispatch — `elif` 86개 → 26개 | ✅ |
| 검증 | 6개 실기기 테스트 — 모든 엔티티 정상 생성 확인 | ✅ |

---

## Git 브랜치

- 브랜치: `feature/service-mapping` (기준: `main`)
- 최근 커밋:
  - `3324694` fix: demandresponse domain을 select에서 제외
  - `931d438` refactor: 모든 writable TEMPERATURE_SERVICE를 select로 통합
  - `2ab58f0` refactor(button): Phase 5 data-driven WS button dispatch
  - `8e1cdeb` refactor(platform): Phase 5 data-driven dispatch — binary_sensor + select
  - `6216c8c` refactor(sensor): Phase 5 data-driven standard sensor dispatch
