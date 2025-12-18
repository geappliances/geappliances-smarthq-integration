# Home Assistant Brands PR 제출 가이드

SmartHQ 통합의 공식 로고를 Home Assistant Brands 저장소에 제출하는 방법입니다.

## 준비된 파일

- `icon.png`: 256x256 픽셀 (GE Appliances 아이콘)
- `logo.png`: 512x512 픽셀 (GE Appliances 로고)

## PR 제출 절차

### 1. Home Assistant Brands 저장소 Fork

1. https://github.com/home-assistant/brands 방문
2. 우측 상단의 **Fork** 버튼 클릭
3. 자신의 GitHub 계정으로 Fork

### 2. Fork한 저장소 Clone

```bash
git clone https://github.com/YOUR_USERNAME/brands.git
cd brands
```

### 3. 새 브랜치 생성

```bash
git checkout -b add-smarthq-icons
```

### 4. SmartHQ 폴더 생성 및 파일 복사

```bash
# custom_integrations 폴더로 이동
cd custom_integrations

# smarthq 폴더 생성
mkdir -p smarthq

# 현재 저장소의 icon.png와 logo.png를 복사
# (이 명령은 smarthq 통합 폴더에서 실행)
cp /root/homeassistant/custom_components/smarthq/icon.png custom_integrations/smarthq/
cp /root/homeassistant/custom_components/smarthq/logo.png custom_integrations/smarthq/
```

### 5. 이미지 최적화 (선택사항)

Brands 저장소는 이미지가 최적화되어 있기를 권장합니다:

```bash
# optipng 설치 (이미 설치되어 있을 수 있음)
# Debian/Ubuntu: sudo apt-get install optipng
# macOS: brew install optipng

# 이미지 최적화
optipng -o7 custom_integrations/smarthq/icon.png
optipng -o7 custom_integrations/smarthq/logo.png
```

### 6. 변경사항 커밋

```bash
git add custom_integrations/smarthq/
git commit -m "Add SmartHQ custom integration icons

- Add icon.png (256x256) for SmartHQ integration
- Add logo.png (512x512) for SmartHQ integration
- Domain: smarthq
- Integration: GE Appliances SmartHQ
"
```

### 7. GitHub에 Push

```bash
git push origin add-smarthq-icons
```

### 8. Pull Request 생성

1. GitHub에서 Fork한 저장소로 이동
2. **Compare & pull request** 버튼 클릭
3. PR 제목: `Add SmartHQ custom integration icons`
4. PR 설명 작성:

```markdown
## Summary

Add icons for the SmartHQ custom integration.

## Details

- **Domain**: `smarthq`
- **Integration**: GE Appliances SmartHQ
- **Repository**: https://github.com/geappliances/geappliances-smarthq-integration
- **Icon**: 256x256 PNG
- **Logo**: 512x512 PNG

## Checklist

- [x] Images are PNG format
- [x] Images are optimized for web
- [x] Images have transparent background
- [x] Images are properly trimmed
- [x] Icon is 256x256 pixels
- [x] Logo shortest side is between 128-256 pixels
- [x] Domain name matches integration manifest
```

5. **Create pull request** 클릭

## PR 승인 후

PR이 승인되고 병합되면:

- 이미지는 `https://brands.home-assistant.io/smarthq/icon.png` 에서 접근 가능
- 이미지는 `https://brands.home-assistant.io/smarthq/logo.png` 에서 접근 가능
- Home Assistant가 자동으로 통합의 아이콘을 표시
- 브라우저 캐시 (7일) 및 Cloudflare 캐시 (24시간)로 인해 표시까지 시간이 걸릴 수 있음

## 이미지 요구사항

### Icon
- 정사각형 (1:1 비율)
- 256x256 픽셀 (필수)
- 512x512 픽셀 (선택, `icon@2x.png`)
- PNG 포맷
- 투명 배경 권장

### Logo
- 브랜드 비율 유지
- 짧은 쪽이 128-256 픽셀 (필수)
- 짧은 쪽이 256-512 픽셀 (선택, `logo@2x.png`)
- PNG 포맷
- 투명 배경 권장

## 참고 자료

- [Home Assistant Brands 저장소](https://github.com/home-assistant/brands)
- [기존 geappliances 아이콘](https://github.com/home-assistant/brands/tree/master/custom_integrations/geappliances)
- [이미지 리사이저 도구](https://redketchup.io/image-resizer)
- [PNG 최적화 도구](https://tinypng.com/)

## 문제 해결

### 이미지가 표시되지 않는 경우

1. **캐시 지우기**: 브라우저 하드 새로고침 (Ctrl+F5 또는 Cmd+Shift+R)
2. **도메인 확인**: manifest.json의 domain이 "smarthq"인지 확인
3. **시간 대기**: PR 병합 후 24-48시간 대기 (캐시 때문)
4. **URL 직접 확인**: `https://brands.home-assistant.io/smarthq/icon.png` 접속해보기

### PR이 거절된 경우

일반적인 거절 이유:
- 이미지 크기가 요구사항과 다름
- 이미지 최적화가 안 됨
- 투명 배경이 없음
- 저작권 문제
- Home Assistant 브랜딩 사용 (커스텀 통합은 HA 로고 사용 금지)
