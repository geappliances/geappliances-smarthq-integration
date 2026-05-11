# Service Mapping 자동화 구현 계획

## 배경 및 목적

API로부터 받는 서비스들을 **명시적 mapping table** 기반으로 자동 처리하는 구조로 전환.

### 핵심 원칙
- **Allowlist 방식**: mapping에 없는 serviceType은 노출하지 않음 (factory_reset 등 차단)
- **두 종류의 mapping**: standard(공통 핸들러) / custom(기존 수동 구현)
- **기기별 코드 제거**: serviceType → mapping → entity 생성으로 완전 통일

---

## Mapping 종류

```
serviceType
    ├── "standard" mapping  → 공통 핸들러 재사용 (toggle, binary_sensor 등)
    └── "custom" mapping    → 기존 수동 구현 코드 (coffeebrewer, thermostat 등)
    └── (없음)              → 노출 안 함 (자동 차단)
```

---

## Standard Handler 목록

| Standard Handler | 대상 serviceType 예시 |
|---|---|
| `StandardToggle` | `toggle`, `laundry.toggle.v2` |
| `StandardBinarySensor` | `door`, `filter.v1`, `connect.v1` |
| `StandardSensor` | `temperature`(RO), `integer`(RO), `meter` |
| `StandardSelect` | `mode`, 각종 mode 서비스 |

---

## 구현 단계

### Phase 1: SERVICE_MAPPING Registry 설계 ✅ → 진행 중
- `service_registry.py`에 `SERVICE_MAPPING` dict 추가
- 현재 구현된 모든 serviceType 등록 (standard / custom 분류)
- mapping 없는 serviceType은 자동 차단

### Phase 2: switch.py 파일럿 적용
- `async_setup_entry`의 `elif` 체인 → mapping 기반으로 교체
- Standard handler 클래스 추출 및 검증

### Phase 3: binary_sensor.py 적용
- 동일 방식 적용

### Phase 4: 나머지 플랫폼 순차 적용
- `sensor.py`, `select.py`, `button.py`, `number.py`, `text.py`, `light.py`, `climate.py`, `water_heater.py`

### Phase 5: Standard Handler 클래스 추출
- 중복 코드 제거
- 공통 핸들러로 추상화

---

## SERVICE_MAPPING 구조 예시

```python
SERVICE_MAPPING = {
    # standard: 공통 핸들러로 처리
    "toggle": {
        "type": "standard",
        "platform": "switch",
        "handler": "StandardToggleSwitch",
    },
    "door": {
        "type": "standard",
        "platform": "binary_sensor",
        "handler": "StandardBinarySensor",
        "params": {"device_class": "door"},
    },
    # custom: 기존 수동 구현 클래스 사용
    "coffeebrewer.v1": {
        "type": "custom",
        "platform": ["button", "select"],
        "handler": "CoffeeBrewerV1",
    },
    "thermostat.v1": {
        "type": "custom",
        "platform": "climate",
        "handler": "SmartHQThermostatClimate",
    },
    # mapping 없음 → 자동 차단 (factory_reset 등)
}
```

---

## Git 브랜치 전략

- 브랜치명: `feature/service-mapping`
- 기준: `main`
- 완료 후 `main`에 merge
