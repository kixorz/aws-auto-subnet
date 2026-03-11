"""
AWS CloudFormation Custom Resource handler for subnet calculations.

Supports four resource types:
    Custom::SubnetInfo   — compute subnet details from IP/CIDR
    Custom::SubnetSplit  — split a network into N equal subnets (FLSM)
    Custom::SubnetVLSM   — allocate variable-length subnets (VLSM)

SubnetInfo, SubnetSplit, and SubnetVLSM are output-only: they compute data
and expose it via Fn::GetAtt.  AutoSubnet actually creates, updates, and
deletes EC2 subnets.
"""

import math
import logging

from crhelper import CfnResource

from subnetcalc import (
    calculate_subnet,
    parse_network,
    prefix_for_hosts,
    split_network,
    vlsm_allocate,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

helper = CfnResource()

# We cap the number of indexed subnet keys to stay safely under this limit.
_MAX_INDEXED_SUBNETS = 20


@helper.create
def create(event, context):
    """Handle Create — compute subnet data or create AWS resources."""
    resource_type = event["ResourceType"]
    props = event["ResourceProperties"]

    logger.info("Processing Create for %s with properties: %s", resource_type, props)

    if resource_type == "Custom::SubnetInfo":
        _handle_info(props)
    elif resource_type == "Custom::SubnetSplit":
        _handle_split(props)
    elif resource_type == "Custom::SubnetVLSM":
        _handle_vlsm(props)
    else:
        raise ValueError(f"Unknown resource type: {resource_type}")


@helper.update
def update(event, context):
    """Handle Update — recompute data for calculator types; AutoSubnet does not support updates."""
    resource_type = event["ResourceType"]
    props = event["ResourceProperties"]

    logger.info("Processing Update for %s with properties: %s", resource_type, props)

    if resource_type == "Custom::SubnetInfo":
        _handle_info(props)
    elif resource_type == "Custom::SubnetSplit":
        _handle_split(props)
    elif resource_type == "Custom::SubnetVLSM":
        _handle_vlsm(props)
    else:
        raise ValueError(f"Unknown resource type: {resource_type}")


def _handle_info(props):
    """
    Custom::SubnetInfo

    Properties:
        Network  (str)           — e.g. "192.168.1.0/24" or "10.0.0.0"
        Mask     (str, optional) — e.g. "255.255.255.0" or "24"
        Hosts    (str, optional) — e.g. "50"  (find smallest subnet for N hosts)
    """
    network_str = props["Network"]
    mask_str = props.get("Mask")
    hosts_str = props.get("Hosts")

    if hosts_str:
        hosts = int(hosts_str)
        prefix = prefix_for_hosts(hosts)
        base_ip = network_str if network_str else "0.0.0.0"
        network = parse_network(base_ip, str(prefix))
    elif network_str:
        network = parse_network(network_str, mask_str)
    else:
        raise ValueError("Provide at least 'Network' or 'Hosts' property")

    info = calculate_subnet(network)

    helper.Data["NetworkAddress"] = info.network_address
    helper.Data["BroadcastAddress"] = info.broadcast_address
    helper.Data["FirstUsableHost"] = info.first_usable_host
    helper.Data["LastUsableHost"] = info.last_usable_host
    helper.Data["SubnetMask"] = info.subnet_mask
    helper.Data["WildcardMask"] = info.wildcard_mask
    helper.Data["CidrNotation"] = info.cidr_notation
    helper.Data["PrefixLength"] = str(info.prefix_length)
    helper.Data["TotalAddresses"] = str(info.total_addresses)
    helper.Data["UsableHosts"] = str(info.usable_hosts)
    helper.Data["IpClass"] = info.ip_class
    helper.Data["IsPrivate"] = str(info.is_private)
    helper.Data["BinaryIp"] = info.binary_ip
    helper.Data["BinaryMask"] = info.binary_mask


def _handle_split(props):
    """
    Custom::SubnetSplit

    Properties:
        Network  (str) — e.g. "10.0.0.0/16"
        Count    (str) — e.g. "4"
    """
    network_str = props["Network"]

    count_str = props.get("Count")
    if not count_str:
        azs = props.get("AvailabilityZones", [])
        count = max(len(azs), 1)

        # Round up to the nearest power of 2
        count = 2**math.ceil(math.log2(count))
    else:
        count = max(int(count_str), 1)

    network = parse_network(network_str)
    result = split_network(network, count)

    helper.Data["OriginalNetwork"] = result.original_network
    helper.Data["NewPrefix"] = str(result.new_prefix)
    helper.Data["SubnetCount"] = str(len(result.subnets))

    subnet_cidrs = []
    # Indexed keys for each subnet (capped to avoid 4 KB limit)
    for i, subnet in enumerate(result.subnets[:_MAX_INDEXED_SUBNETS], 1):
        subnet_cidrs.append(subnet.cidr_notation)
        helper.Data[f"Subnet{i}Cidr"] = subnet.cidr_notation
        helper.Data[f"Subnet{i}NetworkAddress"] = subnet.network_address
        helper.Data[f"Subnet{i}FirstHost"] = subnet.first_usable_host
        helper.Data[f"Subnet{i}LastHost"] = subnet.last_usable_host
        helper.Data[f"Subnet{i}BroadcastAddress"] = subnet.broadcast_address

    helper.Data["Subnets"] = subnet_cidrs


def _handle_vlsm(props):
    """
    Custom::SubnetVLSM

    Properties:
        Network  (str) — e.g. "192.168.1.0/24"
        Hosts    (str) — comma-separated, e.g. "100,50,25,10"
    """
    network_str = props["Network"]
    hosts_str = props["Hosts"]

    if not network_str:
        raise ValueError("'Network' property is required")
    if not hosts_str:
        raise ValueError("'Hosts' property is required")

    network = parse_network(network_str)
    host_reqs = [int(h.strip()) for h in hosts_str.split(",")]
    result = vlsm_allocate(network, host_reqs)

    helper.Data["OriginalNetwork"] = result.original_network
    helper.Data["SubnetCount"] = str(len(result.allocated_subnets))
    helper.Data["WastedAddresses"] = str(result.wasted_addresses)

    # Indexed keys (capped)
    for i, subnet in enumerate(result.allocated_subnets[:_MAX_INDEXED_SUBNETS], 1):
        helper.Data[f"Subnet{i}Cidr"] = subnet.cidr_notation
        helper.Data[f"Subnet{i}NetworkAddress"] = subnet.network_address
        helper.Data[f"Subnet{i}FirstHost"] = subnet.first_usable_host
        helper.Data[f"Subnet{i}LastHost"] = subnet.last_usable_host
        helper.Data[f"Subnet{i}BroadcastAddress"] = subnet.broadcast_address
        helper.Data[f"Subnet{i}UsableHosts"] = str(subnet.usable_hosts)


handler = helper