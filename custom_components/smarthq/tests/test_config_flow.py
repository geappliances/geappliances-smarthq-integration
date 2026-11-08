"""Test the SmartHQ config flow."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.smarthq.const import DEFAULT_OPTIONS, DOMAIN, OAUTH2_AUTHORIZE, OAUTH2_TOKEN

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
REDIRECT_URI = "https://example.com/auth/external/callback"


@pytest.fixture(autouse=True)
async def setup_credentials(hass: HomeAssistant) -> None:
    """Register SmartHQ application credentials, as a user would in the UI."""
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(hass, DOMAIN, ClientCredential(CLIENT_ID, CLIENT_SECRET), DOMAIN)


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Keep the created entry from talking to SmartHQ."""
    with patch("custom_components.smarthq.async_setup_entry", return_value=True) as mock_setup:
        yield mock_setup


async def _complete_oauth(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    result: config_entries.ConfigFlowResult,
    access_token: str,
) -> config_entries.ConfigFlowResult:
    """Follow the external OAuth step and return the flow's next result."""
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT_URI}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"] == (
        f"{OAUTH2_AUTHORIZE}?response_type=code&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&state={state}"
    )

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "refresh_token": "mock-refresh-token",
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"])


@pytest.mark.usefixtures("current_request_with_host")
async def test_config_flow_oauth(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """The user flow signs in with SmartHQ and creates an entry with default options."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await _complete_oauth(hass, hass_client_no_auth, aioclient_mock, result, "mock-access-token")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SmartHQ"
    assert result["data"]["auth_implementation"] == DOMAIN
    assert result["data"]["token"]["access_token"] == "mock-access-token"
    assert result["options"] == DEFAULT_OPTIONS
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.usefixtures("current_request_with_host")
async def test_reauth_updates_existing_entry(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    """Re-authenticating stores the new token on the existing entry instead of adding one."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SmartHQ",
        data={
            "auth_implementation": DOMAIN,
            "token": {"access_token": "expired-token", "refresh_token": "old-refresh-token", "expires_at": 0},
        },
        options=DEFAULT_OPTIONS,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _complete_oauth(hass, hass_client_no_auth, aioclient_mock, result, "new-access-token")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert entry.data["token"]["access_token"] == "new-access-token"
