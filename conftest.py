"""Root pytest configuration for the SmartHQ custom integration.

Living at the repository root puts the repo on ``sys.path`` (so tests can
import ``custom_components.smarthq``) and lets every test load the integration
through Home Assistant's loader.
"""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load integrations from ``custom_components``."""
    yield
