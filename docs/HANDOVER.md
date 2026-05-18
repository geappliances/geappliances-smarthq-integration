# SmartHQ Integration — 작업 인수인계 (2026-05-18)

> **목적**: 새 대화창에서 이 파일을 읽어 이전 작업 컨텍스트를 즉시 파악하기 위한 핸드오버 문서.

---

## 1. 프로젝트 개요

GE Appliances SmartHQ HA Custom Integration.
`serviceType` 기반 아키텍처로 entity를 자동 생성하며, `service_registry.py`의
allowlist에 등록된 서비스만 entity를 만들어 노이즈를 차단.

### 핵심 원칙
- `deviceType` 하드코딩 **없음** — `serviceType`만으로 entity 자동 생성
- `service_registry.py` allowlist에 없는 serviceType → entity 생성 안 함
- `make_unique_id(device_id, service_id, suffix)` → `{device_id}_{service_id}_{suffix}`
- 새 device 추가 시 integration reload만으로 자동 매핑

---

## 2. 환경 정보

| 항목 | 값 |
|---|---|
| Repository | `geappliances/geappliances-smarthq-integration` |
| 현재 작업 브랜치 | `feature/service-mapping` |
| main 최신 tag | `v1.1.0` (2026-05-18 릴리즈) |
| HA 파일 경로 | `/root/homeassistant/custom_components/smarthq/` |
| git 저장소 경로 | `/root/homeassistant/geappliances-smarthq-integration/custom_components/smarthq/` |
| git 계정 | `Jaby-Firstbuild <jaebong.lee@geappliances.com>` (global config 설정 완료) |

### 작업 흐름
```bash
# 1. HA 파일 수정 후 repo에 동기화
cp /root/homeassistant/custom_components/smarthq/button.py \
   /root/homeassistant/geappliances-smarthq-integration/custom_components/smarthq/button.py

# 2. 커밋 & push (feature 브랜치)
cd /root/homeassistant/geappliances-smarthq-integration
git add custom_components/smarthq/button.py
git commit -m "fix: 설명"
git push origin feature/service-mapping

# 3. HA 재시작
ha core restart
```

### main merge & release 시점
수정사항이 충분히 쌓이고 안정성이 검증되면:
```bash
git checkout main
git merge --no-ff feature/service-mapping -m "feat: 기능 설명"
git push origin main
# manifest.json version 올리고 (현재 1.1.0)
git tag -a v1.x.0 -m "v1.x.0"
git push origin main v1.x.0
git checkout feature/service-mapping  # 작업 브랜치로 복귀
```

---

## 3. 실제 보유 기기 (테스트 환경)

| 기기 | device_id prefix | 비고 |
|---|---|---|
| Smoker (Arden) | `b6f41982` | 가장 많이 테스트 |
| Dryer | `7d27fcd8` | — |
| Washer (Top Load) | `1bc2476f` | Remote Start / Start / Stop 테스트 완료 |
| Toaster Oven | `9d2faee3` | — |
| Refrigerator | `a8a7bcac` | — |
| Coffee Brewer | (나머지) | — |

### 서비스 덤프 파일 위치 (`/config/*.json`)
```
/config/smoker_services_dump.json
/config/washerdryer_services_dump.json
/config/dryer_services_dump.json
/config/toasteroven_services_dump.json
/config/refrigerator_services_dump.json
/config/coffeebrewer_services_dump.json
```

---

## 4. feature/service-mapping 브랜치 작업 내역

### Phase 1~4: Service Mapping Allowlist
- `service_registry.py`에 `SERVICE_PLATFORM_MAP` allowlist 도입
- allowlist 미등록 serviceType → 모든 platform에서 entity 생성 skip
- `get_service_mapping()`, `is_platform_mapped()` 헬퍼 함수

### Phase 5: Data-driven dispatch 리팩토링
- `sensor.py`: 46개 elif → `_STANDARD_SENSOR_SPECS` dict 기반 처리
- `binary_sensor.py`, `select.py`: 유사 리팩토링
- `button.py`: `_WS_BUTTON_SPECS` data-driven dispatch

### TEMPERATURE_SERVICE → select 통합
- 모든 writable temperature → number 슬라이더 대신 select 엔티티
- `SmartHQTemperatureSetpointSelect` 클래스

### Demandresponse 차단
- `READONLY_MODE_DOMAINS`에 `demandresponse` 추가 → select 생성 안 함

### Smoker 시간 엔티티 → h+min select
- `SmartHQCookTimeHoursSelect` / `SmartHQCookTimeMinutesSelect`
- `SmartHQAutoWarmHoursSelect` / `SmartHQAutoWarmMinutesSelect`

### 모든 time-unit integer → select 자동 변환
- integer 서비스의 `integerUnits`가 minutes/hours이면 자동으로 select 생성
- `svc_max <= 60` → 단일 select / `> 60` → Hours + Minutes 쌍

### Washer Start/Stop 버튼 개선 (v1.1.0 주요 변경)
- `_SmartHQButtonBase`에 `async_added_to_hass` 추가 → `SIGNAL_DEVICE_UPDATED` 구독 (WS 업데이트 시 available 즉시 재평가)
- `EntityCategory.DIAGNOSTIC` 제거 → Start/Stop이 Controls 탭에 표시
- Start 버튼: `runStatus == "cloud.smarthq.type.runstatus.delayed"`일 때만 활성화
- Stop 버튼: `{standby, idle, off, delayed}` 이외의 상태(running 등)에서 활성화
- factory/restore trigger → `continue`로 완전 차단 (엔티티 생성 안 함)
- firmware 관련 entity(button/binary_sensor/sensor 3종) → 완전 차단
- `laundry.mode.v1` → select 차단 (sensor-only), 원격 제어는 `remotecycleselection` 사용

---

## 5. 차단 정책 (entity 생성 안 함)

| 대상 | 차단 방식 | 사용자 접근 |
|---|---|---|
| `factory` / `restore` trigger | button.py `continue` | ❌ 불가 |
| `icemaker` / `demandresponse` mode | `READONLY_MODE_DOMAINS` → `continue` | ❌ 불가 |
| Firmware upgrade button | button.py `continue` | ❌ 불가 |
| Firmware update binary sensor | binary_sensor.py `continue` | ❌ 불가 |
| Firmware version/status sensors | sensor.py spec 주석처리 | ❌ 불가 |
| `laundry.mode.v1` select | service_registry `platform: "sensor"` | ❌ select 불가 |
| `early.*` (temperature/time) | `disabled_by_default=True` | ✅ 수동 활성화 가능 |

---

## 6. 핵심 파일 구조

```
service_registry.py   — 서비스/커맨드 상수 + allowlist + make_unique_id()
                        READONLY_MODE_DOMAINS: icemaker, demandresponse
                        SWITCH_MODE_DOMAINS: 스위치용 mode 도메인
coordinator.py        — 1회 full fetch (update_interval=None)
ws_client.py          — WS 실시간 → store[device_id]["snapshot"] 갱신
                        SIGNAL_DEVICE_UPDATED 발행
__init__.py           — bootstrap: coordinator → store → ws → platforms
button.py             — trigger / coffeebrewer / dishwasher / mixer
                        _SmartHQButtonBase: SIGNAL_DEVICE_UPDATED 구독
                        SmartHQTriggerButton.available:
                          laundry 기기 → runStatus 기반
                          기타 기기   → trigger.state.disabled 플래그 기반
select.py             — mode / cooking.mode.v1 / temperature setpoint /
                        time selects (h+min) / laundry.remotecycleselection 등
sensor.py             — _STANDARD_SENSOR_SPECS dict 기반 (firmware 제외)
number.py             — 비-time integer (time은 select.py가 처리)
switch.py             — toggle / mode(switch domain) / laundry.toggle.v2
binary_sensor.py      — door / filter / dishwasher 등 (firmware 제외)
climate.py            — thermostat.v1
light.py              — color / cooking.prorange.accent.light
text.py               — string(R/W)
water_heater.py       — waterheater.v1
```

### 데이터 흐름
```
HA 시작
  └─ coordinator.async_config_entry_first_refresh()
       └─ API: GET /v2/device/{id} → services[] → store[did]["snapshot"] 초기화
  └─ 각 platform async_setup_entry()
       └─ services[] 스캔 → allowlist 체크 → entity 생성
  └─ ws_client 연결 (cloud_push)
       └─ WS 이벤트 → store[did]["snapshot"]["services"][service_id] 갱신
       └─ SIGNAL_DEVICE_UPDATED 발행 → entity.async_write_ha_state()
```

> **중요**: WS 스냅샷 `snap["services"]`는 `{ service_id: {state_fields} }` 구조.
> `serviceType` 키 없음. entity에서 snapshot 조회 시 `self._service_id`로 직접 접근.
> index 조회: `snap["index"][(serviceType, domainType)] → service_id` (tuple 키)

---

## 7. Washer 서비스 매핑 현황

| serviceType | domain | 현재 처리 |
|---|---|---|
| `trigger` | `start` | button — `runStatus==delayed`일 때만 활성 |
| `trigger` | `stop` | button — running 등 활성 상태일 때 활성 |
| `toggle` | `door` | binary_sensor (읽기 전용) |
| `integer` | `delay` | select (h+min 자동 변환) |
| `toggle` | `laundry.powersteam` | switch |
| `remotecycleselection` | `laundry.remotecycleselect` | select (Remote Cycle) |
| `toggle` | `uilock` | switch (Control Lock) |
| `stainremoval` | `laundry.stainremoval` | select (Stain Removal) |
| `cycletimer` | `cycle` | sensor (Time Remaining) |
| `toggle` | `laundry.mycycle` | switch |
| `laundry.state.v1` | `laundry` | sensor (runStatus 포함) |
| `laundry.mode.v1` | 각 cycle domain | sensor-only (select 차단) |
| `laundry.downloadablecycle` | `laundry.downloadablecycle` | sensor-only |

---

## 8. GitHub / HACS 현황

| 항목 | 상태 |
|---|---|
| main 최신 | `v1.1.0` (2026-05-18 릴리즈 완료) |
| 작업 브랜치 | `feature/service-mapping` |
| HACS PR | `hacs/default#7484` — maintainer 워크플로우 승인 대기 중 |
| Hassfest Action | ✅ passing |
| Validate Action | ✅ passing |

### HACS PR 대기 관련
- PR 링크 참조: `v1.0.1` 기준이지만, 심사관은 검토 시점의 최신 main을 봄
- "This branch is out-of-date" 경고 → **무시** (충돌 없음, maintainer 요청 없음)
- 우리가 할 일: **없음 — 그냥 대기**

---

## 9. 알려진 구조적 주의사항

1. **WS index 키는 Python tuple**: `snap["index"][(stype, dom)]`
   JSON 직렬화 시 tuple 키 유실 가능 → WS 업데이트로 재생성됨

2. **중복 서비스 인스턴스**: 일부 기기는 동일 serviceType+domainType이
   `serviceDeviceType`만 다르게 2개 등록됨. platform setup 시 dedup 처리 필요.

3. **cooking.mode.v1 집계**: 기기당 여러 domain 서비스를 하나의 select로 aggregation.
   `cooking_mode_svcs` 리스트로 수집 후 루프 밖에서 엔티티 생성.

4. **button.py `available` 분기**:
   - laundry 기기 (`laundry.state.v1` 있음) → `runStatus` 기반
   - 기타 기기 → `trigger.state.disabled` 플래그 기반

---

## 10. 다음 세션 시작 방법

1. 이 파일 경로 언급:
   `/root/homeassistant/geappliances-smarthq-integration/docs/HANDOVER.md`
2. 원하는 작업 요청

### 잠재적 후속 작업 (우선순위 순)

1. **Washer runStatus 값 전체 목록 확인** (낮은 우선순위)
   - 현재 stop 조건: `not in {standby, idle, off, delayed}`
   - 실제 running 중 `ha core logs | grep TRIGGER_AVAIL`로 정확한 값 확인 권장

2. **`laundry.downloadablecycle` select 추가** (선택)
   - 현재 sensor-only
   - Jeans/Swimwear/Activewear 3개 옵션 select로 추가 가능
   - Remote Start 비활성 시 동작 여부 확인 필요

3. **coordinator.py 진단 코드 정리** (낮은 우선순위)
   - `/config/*.json` file dump 코드 제거 (테스트용 잔존)
   - `[COORD_SVC_AUDIT]` WARNING loop 제거
