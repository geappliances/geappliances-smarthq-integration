# Release Guide for HACS

## Creating the First Release (v1.0.0)

Once the repository is made public, create the first release:

### Via GitHub UI:

1. Go to: https://github.com/geappliances/geappliances-smarthq-integration/releases/new

2. **Tag:** `v1.0.0`
   - Click "Choose a tag"
   - Type: `v1.0.0`
   - Click "Create new tag: v1.0.0 on publish"

3. **Release Title:** `SmartHQ Integration v1.0.0`

4. **Description:**
```markdown
## 🎉 Initial Release

Home Assistant custom integration for GE Appliances SmartHQ connected devices.

### ✨ Features
- **OAuth2 Authentication**: Secure login with SmartHQ Developer credentials
- **Real-time Updates**: WebSocket connection for instant device state changes
- **Coffee Brewer Control**: 
  - Brew Strength selection (Light/Medium/Bold)
  - Brew Size selection (10/12/14 Oz, Carafe)
  - Brew Temperature control (85-95°C)
  - Start/Stop buttons with parameter application
- **Smoker/Arden Support**: 
  - Multiple probe temperature monitoring
  - Cook Target Method selection (Probe/Timer/Manual)
  - Smoke level control
  - Pre-programmed cooking modes
- **Additional Devices**: Oven, Toaster Oven support

### 📦 Supported Devices
- **Coffee Brewer**: 6 entities (sensors, selects, buttons)
- **Smoker (Arden)**: 31 entities (sensors, switches, selects, numbers, buttons, binary sensors)
- **Oven**: ~4 entities
- **Toaster Oven**: ~6 entities

### 📖 Installation

#### Via HACS (Recommended)
1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three-dot menu (⋮) → "Custom repositories"
4. Add repository URL: `https://github.com/geappliances/geappliances-smarthq-integration`
5. Category: "Integration"
6. Click "Add"
7. Find "SmartHQ" in HACS and install

#### Manual Installation
1. Download and extract the latest release
2. Copy the `custom_components/smarthq` folder to your `config/custom_components/` directory
3. Restart Home Assistant

### ⚙️ Setup
1. Get OAuth credentials from [SmartHQ Developer Portal](https://developer.smarthq.com)
2. Add Application Credentials in Home Assistant
3. Add SmartHQ integration
4. Authorize with your SmartHQ account

See [README.md](https://github.com/geappliances/geappliances-smarthq-integration/blob/main/README.md) for detailed instructions.

### 🔧 Requirements
- Home Assistant 2023.9.0 or newer
- SmartHQ account and connected appliances
- OAuth2 application credentials from SmartHQ Developer Portal

### 📝 Notes
- First official release
- Tested with Coffee Brewer and Arden Smoker
- Additional devices supported with dynamic entity creation

### 🐛 Known Issues
None reported yet. Please report issues at: https://github.com/geappliances/geappliances-smarthq-integration/issues
```

5. Click **"Publish release"**

### Via GitHub CLI (Alternative):

```bash
gh release create v1.0.0 \
  --title "SmartHQ Integration v1.0.0" \
  --notes-file RELEASE_NOTES.md \
  --repo geappliances/geappliances-smarthq-integration
```

## Version Numbering

Follow [Semantic Versioning](https://semver.org/):
- **MAJOR.MINOR.PATCH** (e.g., 1.0.0)
- **MAJOR**: Breaking changes
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

## Future Releases

For subsequent releases:
1. Update `version` in `manifest.json`
2. Commit and push changes
3. Create new release with appropriate tag (e.g., v1.1.0, v1.0.1)
4. HACS will automatically detect new versions

## Release Checklist

- [ ] Repository is public
- [ ] All code is committed and pushed
- [ ] Version in manifest.json matches release tag
- [ ] README.md is up to date
- [ ] Create GitHub Release with tag v1.0.0
- [ ] Verify release appears in GitHub Releases page
- [ ] Test installation via HACS custom repository
- [ ] (Optional) Submit to HACS default repository
