# Home Assistant Brands PR Submission Guide

Guide for submitting official SmartHQ integration logos to the Home Assistant Brands repository.

## Prepared Files

- `icon.png`: 256x256 pixels (GE Appliances icon)
- `logo.png`: 512x512 pixels (GE Appliances logo)

## PR Submission Process

### 1. Fork the Home Assistant Brands Repository

1. Visit https://github.com/home-assistant/brands
2. Click the **Fork** button in the top right
3. Fork to your GitHub account

### 2. Clone Your Forked Repository

```bash
git clone https://github.com/YOUR_USERNAME/brands.git
cd brands
```

### 3. Create a New Branch

```bash
git checkout -b add-smarthq-icons
```

### 4. Create SmartHQ Folder and Copy Files

```bash
# Navigate to custom_integrations folder
cd custom_integrations

# Create smarthq folder
mkdir -p smarthq

# Copy icon.png and logo.png from this repository
# (Run this command from the smarthq integration folder)
cp /root/homeassistant/custom_components/smarthq/icon.png custom_integrations/smarthq/
cp /root/homeassistant/custom_components/smarthq/logo.png custom_integrations/smarthq/
```

### 5. Optimize Images (Optional)

The Brands repository recommends optimized images:

```bash
# Install optipng (may already be installed)
# Debian/Ubuntu: sudo apt-get install optipng
# macOS: brew install optipng

# Optimize images
optipng -o7 custom_integrations/smarthq/icon.png
optipng -o7 custom_integrations/smarthq/logo.png
```

### 6. Commit Changes

```bash
git add custom_integrations/smarthq/
git commit -m "Add SmartHQ custom integration icons

- Add icon.png (256x256) for SmartHQ integration
- Add logo.png (512x512) for SmartHQ integration
- Domain: smarthq
- Integration: GE Appliances SmartHQ
"
```

### 7. Push to GitHub

```bash
git push origin add-smarthq-icons
```

### 8. Create Pull Request

1. Navigate to your forked repository on GitHub
2. Click the **Compare & pull request** button
3. PR Title: `Add SmartHQ custom integration icons`
4. PR Description:

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

5. **Create pull request** button

## After PR Approval

Once the PR is approved and merged:

- Images will be accessible at `https://brands.home-assistant.io/smarthq/icon.png`
- Images will be accessible at `https://brands.home-assistant.io/smarthq/logo.png`
- Home Assistant will automatically display the integration's icon
- May take time to appear due to browser cache (7 days) and Cloudflare cache (24 hours)

## Image Requirements

### Icon
- Square aspect ratio (1:1)
- 256x256 pixels (required)
- 512x512 pixels (optional, `icon@2x.png`)
- PNG format
- Transparent background preferred

### Logo
- Maintain brand aspect ratio
- Shortest side 128-256 pixels (required)
- Shortest side 256-512 pixels (optional, `logo@2x.png`)
- PNG format
- Transparent background preferred

## References

- [Home Assistant Brands Repository](https://github.com/home-assistant/brands)
- [Existing geappliances icons](https://github.com/home-assistant/brands/tree/master/custom_integrations/geappliances)
- [Image Resizer Tool](https://redketchup.io/image-resizer)
- [PNG Optimization Tool](https://tinypng.com/)

## Troubleshooting

### Icons Not Displaying

1. **Clear Cache**: Hard refresh browser (Ctrl+F5 or Cmd+Shift+R)
2. **Verify Domain**: Confirm manifest.json domain is "smarthq"
3. **Wait**: Allow 24-48 hours after PR merge (due to caching)
4. **Direct URL Check**: Visit `https://brands.home-assistant.io/smarthq/icon.png` directly

### PR Rejected

Common rejection reasons:
- Image size does not meet requirements
- Images not optimized
- Missing transparent background
- Copyright issues
- Using Home Assistant branding (custom integrations must not use HA logos)
