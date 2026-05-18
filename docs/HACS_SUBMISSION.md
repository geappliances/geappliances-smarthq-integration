# HACS Submission Guide

Guide for submitting SmartHQ integration to HACS.

## Two Ways to Use with HACS

### Option 1: Custom Repository (Immediate)
Users can add your integration immediately as a custom repository.

**Users install via:**
1. HACS → Integrations
2. Click three-dot menu (⋮) → Custom repositories
3. Repository: `https://github.com/geappliances/geappliances-smarthq-integration`
4. Category: Integration
5. Click "Add"
6. Find "SmartHQ" and click "Download"

**Advantages:**
- Available immediately after going public
- No waiting for HACS team approval
- Full control over updates

### Option 2: HACS Default Repository (Recommended for visibility)
Submit to HACS default repository for wider visibility.

## Submitting to HACS Default Repository

### Prerequisites (Must be completed first)
- [x] Repository is public
- [x] hacs.json file exists
- [x] manifest.json with correct URLs
- [x] README.md with installation instructions
- [ ] GitHub Release created (v1.0.0)
- [ ] Repository description set
- [ ] Repository topics added

### Submission Process

#### Step 1: Verify Requirements
Check your repository meets all HACS requirements:
- https://www.hacs.xyz/docs/publish/start/

#### Step 2: Fork HACS Default Repository
1. Go to: https://github.com/hacs/default
2. Click "Fork" button
3. Fork to your account

#### Step 3: Create Branch
```bash
git clone https://github.com/YOUR_USERNAME/default.git
cd default
git checkout -b add-smarthq-integration
```

#### Step 4: Add Your Integration
Edit the file: `integration` (not a file extension)

Add this entry to the JSON array:
```json
{
  "name": "geappliances/geappliances-smarthq-integration",
  "category": "integration"
}
```

**Important:** Maintain alphabetical order in the list.

#### Step 5: Commit and Push
```bash
git add integration
git commit -m "Add SmartHQ integration"
git push origin add-smarthq-integration
```

#### Step 6: Create Pull Request
1. Go to: https://github.com/hacs/default/pulls
2. Click "New pull request"
3. Click "compare across forks"
4. Select your fork and branch
5. Title: `Add SmartHQ integration`
6. Description:
```markdown
## Integration Details
- **Name**: SmartHQ
- **Domain**: smarthq
- **Repository**: https://github.com/geappliances/geappliances-smarthq-integration
- **Category**: Integration

## Description
Home Assistant custom integration for GE Appliances SmartHQ connected devices including Coffee Brewer, Smoker, Oven, and Toaster Oven.

## Checklist
- [x] Repository is public
- [x] hacs.json present
- [x] manifest.json valid
- [x] README.md with installation instructions
- [x] GitHub Release created
- [x] Repository has description
- [x] Repository has topics
- [x] Integration domain matches repository structure
```

7. Click "Create pull request"

#### Step 7: Wait for Review
- HACS team will review your submission
- They may request changes
- Respond to feedback promptly
- Once approved, your integration appears in HACS default

### Review Timeline
- Typically 1-7 days
- Could be longer during busy periods
- Check PR comments for any requests

## After Acceptance

Once accepted into HACS default:
- Integration appears in HACS search
- Users can install without adding custom repository
- Automatic update notifications
- Featured in HACS store

## Updating Your Integration

After HACS acceptance:
1. Make code changes
2. Update version in `manifest.json`
3. Commit and push to GitHub
4. Create new GitHub Release
5. HACS automatically detects new version
6. Users get update notifications

## Support and Questions

- **HACS Discord**: https://discord.gg/apgchf8
- **HACS Discussions**: https://github.com/hacs/integration/discussions
- **Documentation**: https://www.hacs.xyz/

## Monitoring

After submission:
- Watch your PR: https://github.com/hacs/default/pulls
- Monitor Issues: https://github.com/geappliances/geappliances-smarthq-integration/issues
- Track installations (GitHub insights)

## Marketing Your Integration

- Post on Home Assistant Community Forum
- Share on Home Assistant subreddit (r/homeassistant)
- Write blog post or tutorial
- Share on social media
- Add to Home Assistant Brands (already done!)
