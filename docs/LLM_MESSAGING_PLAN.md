# LLM Tools & Messaging Control — Implementation Plan

> Last updated: 2026-06-11
> Status: Planning (pre-implementation)
> Scope: Add natural-language control of Home Assistant (incl. SmartHQ devices)
> via LLM tools, the built-in Assist text UI, and an external Telegram bot.

---

## 1. Decisions (locked)

| Topic | Decision |
|---|---|
| LLM provider | **Cloud first** (OpenAI / Google Gemini) — accuracy priority |
| Messenger | **Telegram first** (built-in `telegram_bot`); WhatsApp deferred |
| Entity scope | **Expose all entities EXCEPT locks / security domains** |
| Text UI | Reuse HA built-in **Assist** (no custom UI) |
| Cross-device control | Delegate to HA built-in **`llm.AssistAPI`**; SmartHQ adds domain tools only |

---

## 2. Architecture Overview

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  Telegram   │────▶│  HA telegram_bot  │────▶│ conversation.process│
│   user      │◀────│   (incoming msg)  │◀────│   (Assist pipeline) │
└─────────────┘     └──────────────────┘     └─────────┬──────────┘
                                                        │
                          ┌─────────────────────────────▼─────────────┐
                          │      Conversation agent (OpenAI/Gemini)    │
                          │            uses LLM API tools              │
                          └──────┬───────────────────────┬────────────┘
                                 │                        │
                  ┌──────────────▼──────┐      ┌──────────▼─────────────┐
                  │  llm.AssistAPI      │      │  SmartHQ custom LLM API │
                  │ (all exposed HA     │      │ (appliance-domain tools)│
                  │  entities, generic) │      │  registered by smarthq  │
                  └──────────┬──────────┘      └──────────┬─────────────┘
                             │                            │
                  ┌──────────▼────────────────────────────▼─────────────┐
                  │              Home Assistant entities                 │
                  │   (SmartHQ climate/switch/select/... + others)       │
                  └──────────────────────────────────────────────────────┘
                                  ▲ Security gate (allowlist, confirmation,
                                    exposure filter) applied at every layer
```

Key principle: **Generic cross-device control is provided by HA's built-in
`llm.AssistAPI`.** SmartHQ only contributes a small set of appliance-specific
tools where domain knowledge (cycles, modes, safety) improves accuracy.

---

## 3. Phased Delivery

### Phase 1 — Text control via Assist + Cloud LLM (no new code in smarthq)
Configuration-only; validates the foundation before writing custom tools.
1. Install a Conversation agent integration:
   - **OpenAI Conversation** or **Google Generative AI Conversation** (HA built-in).
2. In the agent options, set **Control Home Assistant** → enable the
   **Assist LLM API**.
3. Configure **entity exposure**: Settings → Voice assistants → Expose.
   Expose all desired entities; **explicitly exclude** `lock.*`,
   `alarm_control_panel.*`, `cover.*` garage/security, and any sensitive scripts.
4. Test in the HA Assist chat (sidebar) with text commands.

**Exit criteria:** Natural-language text commands control non-sensitive entities
through the Assist UI.

### Phase 2 — SmartHQ domain LLM tools
Add a custom LLM API + tools in the smarthq integration.
- New module: `custom_components/smarthq/llm_api.py`
- Registers a `SmartHQLLMAPI(llm.API)` exposing `llm.Tool` subclasses:
  - `start_cycle` — start an appliance cycle (washer/dryer/dishwasher) with a
    named program + options; maps to existing `select`/`button`/`number` entities.
  - `get_appliance_status` — structured status (cycle, remaining time, faults).
  - `set_mode` — set mode/temperature for supported services.
- Tools resolve targets via existing SmartHQ entity/coordinator data; no new
  cloud calls beyond the current `api.py` paths.
- Register/unregister in `__init__.py` `async_setup_entry` / `async_unload_entry`.

**Exit criteria:** LLM can perform appliance-specific actions more reliably than
generic Assist (verified against washer/dryer/dishwasher fixtures).

### Phase 3 — Telegram bot gateway + security gate
- Configure HA built-in `telegram_bot` (polling or webhook) with bot token in
  `secrets.yaml`.
- Route incoming text → `conversation.process` via an automation, or a thin
  helper that enforces the security gate (Section 5).
- Reply with the agent's response.

**Exit criteria:** Authorized Telegram users control non-sensitive entities;
unauthorized chat IDs are rejected; dangerous actions require confirmation.

### Phase 4 — WhatsApp (optional / deferred)
- Requires WhatsApp Business Cloud API (Meta) or Twilio gateway.
- Constraints: business verification, cost, 24h messaging window, template
  messages. Re-evaluate after Phases 1–3 are stable.

---

## 4. New / Changed Files

| File | Type | Purpose |
|---|---|---|
| `custom_components/smarthq/llm_api.py` | new | `SmartHQLLMAPI` + `llm.Tool` definitions |
| `custom_components/smarthq/llm_security.py` | new | exposure filter, action allowlist, confirmation logic |
| `custom_components/smarthq/__init__.py` | edit | register/unregister LLM API on setup/unload |
| `custom_components/smarthq/const.py` | edit | constants: blocked domains, dangerous-action list |
| `custom_components/smarthq/strings.json` / `translations/en.json` | edit | tool/option descriptions if user-facing |
| `docs/LLM_MESSAGING_PLAN.md` | new | this document |
| (config) `configuration.yaml` / `secrets.yaml` | edit | `telegram_bot`, conversation agent, automation |

> SmartHQ ships as a HACS custom integration. **Telegram + conversation agent
> configuration lives in the HA instance config, not in the integration repo**,
> so it stays out of the published package.

---

## 5. Security Design (mandatory)

| # | Control | Implementation |
|---|---|---|
| 1 | **Chat allowlist** | Only pre-approved Telegram `chat_id`s accepted; all others ignored + logged. |
| 2 | **Sensitive-domain block** | Never expose `lock`, `alarm_control_panel`, security `cover`, `camera` recording. Enforced at exposure config AND in `llm_security.py` as defense-in-depth. |
| 3 | **Confirmation for dangerous actions** | Oven/cooktop start, bulk shutoffs, anything in `DANGEROUS_ACTIONS` requires a second confirming message. |
| 4 | **Prompt-injection hardening** | System prompt forbids acting on instructions embedded in entity names/states; tools validate arguments against allowlists, not free strings. |
| 5 | **Secrets hygiene** | Bot token + LLM API key in `secrets.yaml` only; never logged; rotate on suspicion. |
| 6 | **Rate limiting / quota** | Per-chat message + LLM-call quota to prevent spam/cost abuse. |
| 7 | **Data minimization** | Send only needed entity context to the cloud LLM; strip PII (names, locations) where possible. |
| 8 | **Audit logging** | Log every command, user, resolved action, and outcome. |
| 9 | **Physical-safety respect** | Honor SmartHQ's own remote-start restrictions; do not bypass appliance safety locks. |

---

## 6. Open Questions / Risks
- Cloud LLM cost ceiling and provider choice (OpenAI vs Gemini) — pricing/latency.
- Telegram delivery mode: polling (simpler, no public URL) vs webhook (needs HTTPS).
- Confirmation UX over text (e.g., reply "YES" within N seconds).
- WhatsApp business onboarding cost/timeline if Phase 4 is approved.

---

## 7. Critical Review & Counterarguments

A deliberately skeptical assessment was performed. These concerns are accepted
as real and are addressed by the mitigations listed in each row. The project
proceeds with these mitigations baked in.

| # | Criticism | Why it matters | Mitigation adopted |
|---|---|---|---|
| 1 | **Feature overlap with HA core** — Assist, `llm.AssistAPI`, and `telegram_bot` already exist; users can get ~90% via configuration alone. | The integration's added value narrows to Phase 2 domain tools. | Keep Phase 1 **config-only**; the integration ships **only** appliance-specific tools where domain knowledge measurably beats generic Assist. Validate that delta against fixtures before shipping. |
| 2 | **Scope creep** — SmartHQ is a "GE appliance → HA entity" hub; adding messenger/LLM/security policy blurs its identity. | Maintenance + review burden, identity erosion. | Messenger + agent config stays in the **HA instance config, not the package**. Integration contributes only `llm_api.py` / `llm_security.py`. |
| 3 | **HACS distribution mismatch** — published package vs per-instance secrets (API keys, bot token, exposure policy). | Deployable code and user config get entangled. | Strict separation: no secrets/config in repo; tools are inert until the user wires up an agent. Document this boundary. |
| 4 | **Codeowner conflict** — GE Appliances (`@geappliances`) may reject third-party messenger/LLM control in the official integration. | Risk of PR rejection / unmaintained fork. | Treat LLM tools as **opt-in and self-contained**; be prepared to split into a **separate repo / HA package** if upstream declines. |
| 5 | **Prompt injection is unsolved** — system-prompt guards are unreliable; malicious entity names/states can hijack the LLM. | Security defense is weaker than it looks. | Tools validate arguments against **allowlists, not free strings**; sensitive domains blocked in code (defense-in-depth), not just prompt text. |
| 6 | **Asymmetric physical-safety risk** — a wrong oven/cooktop start = fire/flood; LLM nondeterminism + physical appliances is dangerous. | Loss far outweighs convenience gain. | High-risk appliance actions default to **read-only/monitoring**; any control requires explicit `DANGEROUS_ACTIONS` confirmation; honor SmartHQ remote-start restrictions. |
| 7 | **Unpredictable cloud LLM cost** — spam can cause a cost spike; adds always-on billing to a previously free integration. | Operational sustainability. | Per-chat **rate limiting + quota**; document local (Ollama) option to remove cost/privacy exposure. |
| 8 | **Maintenance burden** — HA `llm` API is new (2024.6+) and may have breaking changes, plus LLM/Telegram API churn. | Long-term upkeep. | Isolate volatile surface in `llm_api.py`; pin/guard against API changes; keep tool surface minimal. |
| 9 | **WhatsApp is impractical** — no official integration, Meta business verification, cost, 24h window/template rules. | Low ROI for an open-source project. | **Deferred to Phase 4 / de-prioritized**; Telegram-only for v1. |
| 10 | **UX may underdeliver** — NL control demos well but misrecognition/latency push users back to dashboards. | Adoption risk. | Ship incrementally with explicit exit criteria; measure real usage before expanding. |

**Decision:** Proceed with the original plan, with the above mitigations treated
as non-negotiable acceptance criteria. Physical-appliance control stays
conservative (monitoring-first + confirmation gates).

---

## 8. Recommended Next Action
Proceed with **Phase 1** (configuration-only) to validate the foundation, then
implement **Phase 2** custom tools in `llm_api.py`. Phases are independently
shippable and each has explicit exit criteria above.
