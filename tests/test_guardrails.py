from __future__ import annotations

import pytest

from sprinter.integrations.adx import AdxClient
from sprinter.integrations.splunk import SplunkClient


def test_splunk_requires_allowlisted_index(settings) -> None:
    client = SplunkClient(settings.model_copy(update={"splunk_allowed_indexes": "security,endpoint"}))
    assert client.validate('index="security" EventID=1').startswith("search ")
    with pytest.raises(ValueError, match="explicit index"):
        client.validate("EventID=1")
    with pytest.raises(ValueError, match="not allowed"):
        client.validate("index=internal")
    with pytest.raises(ValueError, match="disallowed command"):
        client.validate("index=security | collect index=other")


def test_adx_is_read_only_and_table_allowlisted(settings) -> None:
    client = AdxClient(settings.model_copy(update={"adx_allowed_tables": "DeviceEvents,SigninLogs"}))
    assert client.validate("DeviceEvents | take 5") == "DeviceEvents | take 5"
    with pytest.raises(ValueError, match="allowlisted"):
        client.validate("OtherTable | take 5")
    with pytest.raises(ValueError, match="read-only"):
        client.validate("DeviceEvents | into Output")
    with pytest.raises(ValueError, match="read-only"):
        client.validate(".drop table DeviceEvents")
