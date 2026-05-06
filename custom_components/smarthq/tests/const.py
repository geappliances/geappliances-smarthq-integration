"""Constants for SmartHQ tests."""

MOCK_CONFIG = {
    "auth_implementation": "smarthq",
}

MOCK_DEVICE_INFO = {
    "deviceId": "test_device_123",
    "deviceType": "cloud.smarthq.device.smoker",
    "nickname": "Test Smoker",
    "model": "Test Model",
    "firmwareRevision": "1.0.0",
}

MOCK_SERVICES = {
    "service_123": {
        "serviceType": "cloud.smarthq.service.cooking.state.v1",
        "domainType": "cloud.smarthq.domain.cooking",
        "serviceDeviceType": "cloud.smarthq.device.smoker",
        "state": {
            "cookingStatus": "ready",
            "runStatus": "active",
            "remoteEnable": True,
        },
    }
}
