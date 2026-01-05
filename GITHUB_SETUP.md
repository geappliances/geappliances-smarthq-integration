# GitHub Repository Setup for HACS

This document outlines the required GitHub repository settings for HACS publication.

## Required Settings

### 1. Repository Visibility
- [ ] **Change to Public**
  - Go to: Settings → General → Danger Zone
  - Click "Change visibility" → "Make public"
  - Confirm by typing repository name

### 2. Repository Description
- [ ] **Add Description**
  - Go to: Settings → General
  - Description: `Home Assistant custom integration for GE Appliances SmartHQ connected devices`
  - Click "Save"

### 3. Repository Topics
- [ ] **Add Topics**
  - Go to: Repository main page
  - Click the gear icon (⚙️) next to "About"
  - Add the following topics:
    - `home-assistant`
    - `hacs`
    - `home-assistant-integration`
    - `smart-home`
    - `ge-appliances`
    - `smarthq`
    - `iot`
    - `custom-integration`
  - Click "Save changes"

### 4. Issues and Discussions
- [ ] **Enable Issues**
  - Go to: Settings → General → Features
  - Check "Issues"
- [ ] **Enable Discussions** (Optional but recommended)
  - Check "Discussions"

### 5. Branch Protection (Optional but recommended)
- [ ] **Protect main branch**
  - Go to: Settings → Branches
  - Add rule for `main` branch
  - Enable:
    - Require pull request reviews before merging
    - Require status checks to pass

### 6. GitHub Pages (Optional)
- [ ] **Enable Pages** for documentation
  - Go to: Settings → Pages
  - Source: Deploy from a branch
  - Branch: `main` / `docs` (if you create docs folder)

## Verification Checklist

After making repository public:
- [ ] Repository accessible at: https://github.com/geappliances/geappliances-smarthq-integration
- [ ] Description visible on main page
- [ ] Topics displayed below description
- [ ] Issues enabled and accessible
- [ ] README.md renders correctly
- [ ] icon.png and logo.png visible in repository

## Ready for HACS?

Once all above settings are complete:
1. Create GitHub Release (see RELEASE_GUIDE.md)
2. Test with HACS custom repository
3. (Optional) Submit to HACS default repository
