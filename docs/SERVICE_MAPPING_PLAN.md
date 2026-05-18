# Service Mapping 기반 엔티티 생성 규칙

> 최종 업데이트: 2026-05-18 (v1.1.0)

## 개요

SmartHQ 통합은 GE 가전기기 API로부터 수신한 서비스 목록을
**`SERVICE_MAPPING` Allowlist** 기반으로 Home Assistant 엔티티로 변환합니다.

### 핵심 원칙
- **Allowlist 방식**: `SERVICE_MAPPING`에 없는 serviceType은 자동 차단
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

## 차단 정책 (entity 생성 안 함)

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

## domainType 기반 세부 분기 규칙

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
```

### `integer` 서비스

```
integer 서비스
    ├─ integerUnits에 hour/minute 포함  → select (h+min 쌍 또는 단일)
    │     svc_max <= 60  → 단일 select
    │     svc_max > 60   → Hours select + Minutes select 쌍
    └─ 그 외                         → number (슬라이더)
```

### `trigger` 서비스 (button)

```
trigger 서비스
    ├─ domain에 "factory" 또는 "restore" 포함  → 완전 차단 (생성 안 함)
    ├─ laundry 기기 (laundry.state.v1 있음)
    │     domain.start  → runStatus == "delayed" 일 때만 활성화
    │     domain.stop   → runStatus ∉ {standby, idle, off, delayed} 일 때 활성화
    └─ 기타 기기        → trigger.state.disabled 플래그 기반
```

### `toggle` 서비스

```
toggle 서비스
    ├─ LOCK_DOMAINS      → switch (device_class: lock)
    ├─ BRIGHTNESS_DOMAINS → light
    └─ 그 외              → switch (일반)
```

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
| v1.1.0 | Washer Start/Stop, firmware 차단, time select 변환 | ✅ |

---

## Git 현황

- 작업 브랜치: `feature/service-mapping`
- main 최신: `v1.1.0` (2026-05-18)
- 최근 커밋:
  - `308f893` fix: block all firmware entities from creation
  - `ef2f23e` fix(button): block factory/restore triggers from entity creation
  - `87284a7` fix(washer): Start/Stop button availability based on runStatus
  - `47e6fd9` refactor(select): convert all time-unit integers to select entities
  - `bbc8bc5` refactor(smoker): replace time number entities with h+min select entities
