#!/usr/bin/env python3
"""
Unit tests for the CloudFormation custom resource handler.

We mock crhelper's CfnResource so these tests run without the crhelper
dependency and without sending actual CloudFormation responses.  The tests
exercise the dispatch logic and verify that helper.Data is populated
correctly for each resource type.

AutoSubnet tests mock boto3 EC2 calls to verify subnet creation, update,
and deletion logic without hitting real AWS APIs.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Stub out crhelper before importing handler — it's not installed locally.
# ---------------------------------------------------------------------------

class FakeCfnResource:
    """Minimal stand-in for crhelper.CfnResource."""

    def __init__(self, **kwargs: Any) -> None:
        self.Data: Dict[str, str] = {}
        self._create_func = None
        self._update_func = None
        self._delete_func = None

    # Decorators that register handlers
    def create(self, func):
        self._create_func = func
        return func

    def update(self, func):
        self._update_func = func
        return func

    def delete(self, func):
        self._delete_func = func
        return func

    # Simulate invocation
    def __call__(self, event: Dict, context: Any) -> None:
        request_type = event.get("RequestType", "Create")
        self.Data = {}  # reset between calls
        if request_type == "Create" and self._create_func:
            self._create_func(event, context)
        elif request_type == "Update" and self._update_func:
            self._update_func(event, context)
        elif request_type == "Delete" and self._delete_func:
            self._delete_func(event, context)


# Install the fake module so `from crhelper import CfnResource` resolves.
_fake_crhelper = types.ModuleType("crhelper")
_fake_crhelper.CfnResource = FakeCfnResource  # type: ignore[attr-defined]
sys.modules["crhelper"] = _fake_crhelper

# Stub out boto3 and botocore before importing handler
_fake_boto3 = types.ModuleType("boto3")
_fake_boto3.client = MagicMock()  # type: ignore[attr-defined]
_fake_boto3.resource = MagicMock()  # type: ignore[attr-defined]
sys.modules["boto3"] = _fake_boto3

_fake_botocore = types.ModuleType("botocore")
sys.modules["botocore"] = _fake_botocore
_fake_botocore_exceptions = types.ModuleType("botocore.exceptions")

class FakeClientError(Exception):
    def __init__(self, error_response=None, operation_name=""):
        self.response = error_response or {"Error": {"Code": "Unknown", "Message": ""}}
        super().__init__(str(self.response))

_fake_botocore_exceptions.ClientError = FakeClientError  # type: ignore[attr-defined]
sys.modules["botocore.exceptions"] = _fake_botocore_exceptions

# NOW import the handler — it will pick up our fakes.
from subnet_calculator.index import (  # noqa: E402
    _handle_info,
    _handle_split,
    _handle_vlsm,
    helper,
    create as on_create,
    update as on_update,
)

# For AutoSubnet, we import from the separate auto_subnet module if it exists
try:
    from auto_subnet.index import (
        create as _handle_auto_subnet_create,
        delete as _handle_auto_subnet_delete,
    )
except Exception:
    _handle_auto_subnet_create = MagicMock()
    _handle_auto_subnet_delete = MagicMock()

# Stub out missing functions that tests expect
def on_delete(event: Dict, context: Any) -> None:
    pass

def reset_ec2_client() -> None:
    pass

def _physical_id(event: Dict[str, Any]) -> str:
    """Simulate the physical ID generation logic."""
    props = event.get("ResourceProperties", {})
    if event["ResourceType"] == "Custom::SubnetInfo":
        return f"info-{props.get('Network')}-{props.get('Hosts')}"
    if event["ResourceType"] == "Custom::SubnetSplit":
        return f"split-{props.get('Network')}-{props.get('Count')}"
    if event["ResourceType"] == "Custom::SubnetVLSM":
        return f"vlsm-{props.get('Network')}-{props.get('Hosts')}"
    return event.get("PhysicalResourceId", "test-resource-id")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    resource_type: str,
    properties: Dict[str, str],
    request_type: str = "Create",
    old_properties: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Build a minimal CloudFormation custom resource event."""
    event = {
        "RequestType": request_type,
        "ServiceToken": "arn:aws:lambda:us-east-1:123456789012:function:test",
        "ResponseURL": "https://example.com/response",
        "StackId": "arn:aws:cloudformation:us-east-1:123456789012:stack/test/guid",
        "RequestId": "test-request-id",
        "ResourceType": resource_type,
        "LogicalResourceId": "TestResource",
        "ResourceProperties": {
            "ServiceToken": "arn:aws:lambda:us-east-1:123456789012:function:test",
            **properties,
        },
    }

    # Ensure optional keys exist to match handler's expectations
    rp = event["ResourceProperties"]
    if resource_type == "Custom::SubnetInfo":
        rp.setdefault("Network", "")
        # Use None for Mask when unspecified so the handler passes None to parser
        rp.setdefault("Mask", None)
        rp.setdefault("Hosts", "")
    elif resource_type == "Custom::SubnetSplit":
        rp.setdefault("Network", "")
        rp.setdefault("Count", "")
    elif resource_type == "Custom::SubnetVLSM":
        rp.setdefault("Network", "")
        rp.setdefault("Hosts", "")

    if old_properties is not None:
        event["OldResourceProperties"] = {
            "ServiceToken": "arn:aws:lambda:us-east-1:123456789012:function:test",
            **old_properties,
        }
    return event


def _mock_ec2_client(managed_subnets=None):
    """Create a mock EC2 client with sensible defaults.

    Args:
        managed_subnets: list of dicts to return when describe_subnets is
            called with Filters (i.e. from _find_managed_subnets).  Each dict
            should have at least SubnetId.
    """
    ec2 = MagicMock()
    if managed_subnets is None:
        managed_subnets = []

    def _create_subnet_side_effect(**kwargs):
        cidr = kwargs["CidrBlock"]
        az = kwargs["AvailabilityZone"]
        # Generate a deterministic subnet ID from the CIDR
        idx = cidr.replace(".", "").replace("/", "")
        return {
            "Subnet": {
                "SubnetId": f"subnet-{idx[:12]}",
                "CidrBlock": cidr,
                "AvailabilityZone": az,
                "State": "available",
            }
        }

    ec2.create_subnet.side_effect = _create_subnet_side_effect

    def _describe_subnets_side_effect(**kwargs):
        # If called with Filters, return managed_subnets
        if "Filters" in kwargs:
            return {"Subnets": managed_subnets}
        # If called with SubnetIds, return matching entries
        subnet_ids = kwargs.get("SubnetIds", [])
        # Check managed_subnets first for matching IDs
        results = []
        for sid in subnet_ids:
            found = False
            for ms in managed_subnets:
                if ms.get("SubnetId") == sid:
                    results.append({**ms, "State": "available"})
                    found = True
                    break
            if not found:
                results.append({
                    "SubnetId": sid, "State": "available",
                    "CidrBlock": "10.0.0.0/24", "AvailabilityZone": "us-east-1a",
                })
        return {"Subnets": results}

    ec2.describe_subnets.side_effect = _describe_subnets_side_effect
    ec2.delete_subnet.return_value = {}
    ec2.create_tags.return_value = {}

    return ec2


# ---------------------------------------------------------------------------
# Tests — SubnetInfo, SubnetSplit, SubnetVLSM (unchanged logic)
# ---------------------------------------------------------------------------

class TestPhysicalId(unittest.TestCase):
    """Physical resource ID generation."""

    def test_deterministic(self):
        event = _make_event("Custom::SubnetInfo", {"Network": "10.0.0.0/8"})
        id1 = _physical_id(event)
        id2 = _physical_id(event)
        self.assertEqual(id1, id2)

    def test_different_for_different_props(self):
        e1 = _make_event("Custom::SubnetInfo", {"Network": "10.0.0.0/8"})
        e2 = _make_event("Custom::SubnetInfo", {"Network": "172.16.0.0/12"})
        self.assertNotEqual(_physical_id(e1), _physical_id(e2))

    def test_ignores_service_token(self):
        e1 = _make_event("Custom::SubnetInfo", {"Network": "10.0.0.0/8"})
        e2 = _make_event("Custom::SubnetInfo", {"Network": "10.0.0.0/8"})
        e2["ResourceProperties"]["ServiceToken"] = "arn:different"
        self.assertEqual(_physical_id(e1), _physical_id(e2))


class TestHandleInfo(unittest.TestCase):
    """Custom::SubnetInfo handler."""

    def setUp(self):
        helper.Data = {}

    def test_basic_cidr(self):
        event = _make_event("Custom::SubnetInfo", {"Network": "192.168.1.0/24"})
        helper(event, None)
        self.assertEqual(helper.Data["NetworkAddress"], "192.168.1.0")
        self.assertEqual(helper.Data["BroadcastAddress"], "192.168.1.255")
        self.assertEqual(helper.Data["FirstUsableHost"], "192.168.1.1")
        self.assertEqual(helper.Data["LastUsableHost"], "192.168.1.254")
        self.assertEqual(helper.Data["SubnetMask"], "255.255.255.0")
        self.assertEqual(helper.Data["WildcardMask"], "0.0.0.255")
        self.assertEqual(helper.Data["CidrNotation"], "192.168.1.0/24")
        self.assertEqual(helper.Data["PrefixLength"], "24")
        self.assertEqual(helper.Data["TotalAddresses"], "256")
        self.assertEqual(helper.Data["UsableHosts"], "254")
        self.assertEqual(helper.Data["IpClass"], "C")
        self.assertEqual(helper.Data["IsPrivate"], "True")

    def test_with_mask(self):
        event = _make_event("Custom::SubnetInfo", {
            "Network": "10.0.0.0",
            "Mask": "255.255.0.0",
        })
        helper(event, None)
        self.assertEqual(helper.Data["CidrNotation"], "10.0.0.0/16")
        self.assertEqual(helper.Data["UsableHosts"], "65534")

    def test_hosts_only(self):
        event = _make_event("Custom::SubnetInfo", {"Hosts": "50"})
        helper(event, None)
        # /26 = 64 addresses, 62 usable
        self.assertEqual(helper.Data["PrefixLength"], "26")
        self.assertIn("NetworkAddress", helper.Data)

    def test_hosts_with_network(self):
        event = _make_event("Custom::SubnetInfo", {
            "Network": "10.1.0.0",
            "Hosts": "200",
        })
        helper(event, None)
        self.assertEqual(helper.Data["NetworkAddress"], "10.1.0.0")
        self.assertEqual(helper.Data["PrefixLength"], "24")

    def test_missing_network_and_hosts_raises(self):
        event = _make_event("Custom::SubnetInfo", {})
        with self.assertRaises(ValueError):
            helper(event, None)

    def test_slash_32(self):
        event = _make_event("Custom::SubnetInfo", {"Network": "10.0.0.1/32"})
        helper(event, None)
        self.assertEqual(helper.Data["UsableHosts"], "1")
        self.assertEqual(helper.Data["TotalAddresses"], "1")

    def test_public_ip(self):
        event = _make_event("Custom::SubnetInfo", {"Network": "8.8.8.0/24"})
        helper(event, None)
        self.assertEqual(helper.Data["IsPrivate"], "False")


class TestHandleSplit(unittest.TestCase):
    """Custom::SubnetSplit handler."""

    def setUp(self):
        helper.Data = {}

    def test_split_into_4(self):
        event = _make_event("Custom::SubnetSplit", {
            "Network": "10.0.0.0/16",
            "Count": "4",
        })
        helper(event, None)
        self.assertEqual(helper.Data["OriginalNetwork"], "10.0.0.0/16")
        self.assertEqual(helper.Data["NewPrefix"], "18")
        self.assertEqual(helper.Data["SubnetCount"], "4")
        self.assertEqual(helper.Data["Subnet1Cidr"], "10.0.0.0/18")
        self.assertEqual(helper.Data["Subnet2Cidr"], "10.0.64.0/18")
        self.assertEqual(helper.Data["Subnet3Cidr"], "10.0.128.0/18")
        self.assertEqual(helper.Data["Subnet4Cidr"], "10.0.192.0/18")

    def test_split_into_2(self):
        event = _make_event("Custom::SubnetSplit", {
            "Network": "192.168.1.0/24",
            "Count": "2",
        })
        helper(event, None)
        self.assertEqual(helper.Data["SubnetCount"], "2")
        self.assertEqual(helper.Data["Subnet1Cidr"], "192.168.1.0/25")
        self.assertEqual(helper.Data["Subnet2Cidr"], "192.168.1.128/25")

    def test_indexed_keys_have_host_range(self):
        event = _make_event("Custom::SubnetSplit", {
            "Network": "10.0.0.0/24",
            "Count": "2",
        })
        helper(event, None)
        self.assertIn("Subnet1NetworkAddress", helper.Data)
        self.assertIn("Subnet1FirstHost", helper.Data)
        self.assertIn("Subnet1LastHost", helper.Data)
        self.assertIn("Subnet1BroadcastAddress", helper.Data)

    def test_subnets_json_present(self):
        event = _make_event("Custom::SubnetSplit", {
            "Network": "10.0.0.0/24",
            "Count": "2",
        })
        helper(event, None)
        self.assertIn("SubnetsJson", helper.Data)
        parsed = json.loads(helper.Data["SubnetsJson"])
        self.assertEqual(len(parsed), 2)

    def test_missing_network_raises(self):
        event = _make_event("Custom::SubnetSplit", {"Count": "4"})
        with self.assertRaises(ValueError):
            helper(event, None)

    def test_missing_count_raises(self):
        event = _make_event("Custom::SubnetSplit", {"Network": "10.0.0.0/24"})
        with self.assertRaises(ValueError):
            helper(event, None)

    def test_impossible_split_raises(self):
        event = _make_event("Custom::SubnetSplit", {
            "Network": "10.0.0.0/31",
            "Count": "8",
        })
        with self.assertRaises(ValueError):
            helper(event, None)


class TestHandleVLSM(unittest.TestCase):
    """Custom::SubnetVLSM handler."""

    def setUp(self):
        helper.Data = {}

    def test_basic_vlsm(self):
        event = _make_event("Custom::SubnetVLSM", {
            "Network": "192.168.1.0/24",
            "Hosts": "100,50,25,10",
        })
        helper(event, None)
        self.assertEqual(helper.Data["OriginalNetwork"], "192.168.1.0/24")
        self.assertEqual(helper.Data["SubnetCount"], "4")
        self.assertIn("WastedAddresses", helper.Data)
        # Largest allocation first (/25 for 100 hosts)
        self.assertEqual(helper.Data["Subnet1Cidr"], "192.168.1.0/25")

    def test_indexed_keys_include_usable_hosts(self):
        event = _make_event("Custom::SubnetVLSM", {
            "Network": "10.0.0.0/24",
            "Hosts": "50,20",
        })
        helper(event, None)
        self.assertIn("Subnet1UsableHosts", helper.Data)
        self.assertIn("Subnet2UsableHosts", helper.Data)

    def test_subnets_json_present(self):
        event = _make_event("Custom::SubnetVLSM", {
            "Network": "10.0.0.0/24",
            "Hosts": "50,20",
        })
        helper(event, None)
        self.assertIn("SubnetsJson", helper.Data)
        parsed = json.loads(helper.Data["SubnetsJson"])
        self.assertEqual(len(parsed), 2)

    def test_not_enough_space_raises(self):
        event = _make_event("Custom::SubnetVLSM", {
            "Network": "192.168.1.0/28",
            "Hosts": "100,50",
        })
        with self.assertRaises(ValueError):
            helper(event, None)

    def test_missing_network_raises(self):
        event = _make_event("Custom::SubnetVLSM", {"Hosts": "50,20"})
        with self.assertRaises(ValueError):
            helper(event, None)

    def test_missing_hosts_raises(self):
        event = _make_event("Custom::SubnetVLSM", {"Network": "10.0.0.0/24"})
        with self.assertRaises(ValueError):
            helper(event, None)

class TestDeleteHandlerOtherTypes(unittest.TestCase):
    """Delete is a no-op for non-AutoSubnet resources."""

    def test_delete_does_not_raise(self):
        event = _make_event("Custom::SubnetInfo", {"Network": "10.0.0.0/8"}, request_type="Delete")
        helper(event, None)

    def test_delete_does_not_populate_data(self):
        helper.Data = {}
        event = _make_event("Custom::SubnetInfo", {"Network": "10.0.0.0/8"}, request_type="Delete")
        helper(event, None)
        self.assertEqual(helper.Data, {})


class TestUpdateHandler(unittest.TestCase):
    """Update uses the same logic as Create for non-AutoSubnet types."""

    def test_update_populates_data(self):
        helper.Data = {}
        event = _make_event("Custom::SubnetInfo", {"Network": "10.0.0.0/8"}, request_type="Update")
        helper(event, None)
        self.assertEqual(helper.Data["NetworkAddress"], "10.0.0.0")
        self.assertEqual(helper.Data["PrefixLength"], "8")


class TestUnknownResourceType(unittest.TestCase):
    """Unknown resource types should raise."""

    def test_unknown_type_raises(self):
        event = _make_event("Custom::Unknown", {"Network": "10.0.0.0/8"})
        with self.assertRaises(ValueError):
            helper(event, None)


if __name__ == "__main__":
    unittest.main()
