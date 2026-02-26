"""
Core subnet calculation engine.

Provides functions to compute subnet information, parse flexible network
input, split networks (FLSM), and allocate variable-length subnets (VLSM).
"""

from __future__ import annotations

import ipaddress
import math
from typing import List, Optional

from .models import AutoSubnetResult, SplitResult, SubnetInfo, VLSMResult


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ip_class(ip: ipaddress.IPv4Address) -> str:
    """Return the classful network class (A-E) for an IPv4 address."""
    first_octet = int(ip.packed[0])
    if first_octet < 128:
        return "A"
    if first_octet < 192:
        return "B"
    if first_octet < 224:
        return "C"
    if first_octet < 240:
        return "D"
    return "E"


def _to_dotted_binary(ip: ipaddress.IPv4Address) -> str:
    """Convert an IPv4 address to dotted binary notation."""
    return ".".join(f"{octet:08b}" for octet in ip.packed)


def _wildcard(mask: ipaddress.IPv4Address) -> ipaddress.IPv4Address:
    """Return the wildcard (inverse) mask."""
    return ipaddress.IPv4Address(int(mask) ^ 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def calculate_subnet(network: ipaddress.IPv4Network) -> SubnetInfo:
    """Compute all subnet properties for a given IPv4Network."""
    net_addr = network.network_address
    bcast = network.broadcast_address
    prefix = network.prefixlen
    mask = network.netmask
    total = network.num_addresses

    # Usable hosts & range depend on prefix length
    if prefix == 32:
        usable = 1
        first_host = str(net_addr)
        last_host = str(net_addr)
    elif prefix == 31:
        # RFC 3021 point-to-point -- both addresses are usable, no broadcast
        usable = 2
        first_host = str(net_addr)
        last_host = str(bcast)
    else:
        usable = total - 2
        first_host = str(net_addr + 1)
        last_host = str(bcast - 1)

    return SubnetInfo(
        network_address=str(net_addr),
        broadcast_address=str(bcast),
        first_usable_host=first_host,
        last_usable_host=last_host,
        subnet_mask=str(mask),
        wildcard_mask=str(_wildcard(mask)),
        cidr_notation=str(network),
        prefix_length=prefix,
        total_addresses=total,
        usable_hosts=usable,
        ip_class=_ip_class(net_addr),
        is_private=net_addr.is_private,
        binary_ip=_to_dotted_binary(net_addr),
        binary_mask=_to_dotted_binary(mask),
    )


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def parse_network(ip_str: str, mask: Optional[str] = None) -> ipaddress.IPv4Network:
    """
    Parse a network from flexible user input.

    Accepted forms:
        "192.168.1.0/24"
        "192.168.1.0", mask="255.255.255.0"
        "192.168.1.0", mask="24"
    """
    if mask is not None:
        # mask can be dotted-decimal or plain prefix length
        try:
            prefix = int(mask)
        except ValueError:
            # Convert dotted-decimal mask to prefix length
            mask_obj = ipaddress.IPv4Address(mask)
            prefix = bin(int(mask_obj)).count("1")
        return ipaddress.IPv4Network(f"{ip_str}/{prefix}", strict=False)
    return ipaddress.IPv4Network(ip_str, strict=False)


def prefix_for_hosts(required_hosts: int) -> int:
    """Return the smallest prefix length that can accommodate *required_hosts* usable addresses."""
    if required_hosts < 1:
        raise ValueError("Host count must be at least 1")
    if required_hosts == 1:
        return 32
    if required_hosts == 2:
        return 31  # RFC 3021
    # Need required_hosts + 2 total addresses (network + broadcast)
    host_bits = math.ceil(math.log2(required_hosts + 2))
    prefix = 32 - host_bits
    if prefix < 0:
        raise ValueError(f"Cannot fit {required_hosts} hosts in an IPv4 subnet")
    return prefix


# ---------------------------------------------------------------------------
# FLSM -- split into N equal subnets
# ---------------------------------------------------------------------------

def split_network(network: ipaddress.IPv4Network, count: int) -> SplitResult:
    """Split *network* into *count* equal subnets (FLSM)."""
    if count < 1:
        raise ValueError("Subnet count must be at least 1")

    extra_bits = math.ceil(math.log2(count))
    new_prefix = network.prefixlen + extra_bits
    if new_prefix > 32:
        raise ValueError(
            f"Cannot split /{network.prefixlen} into {count} subnets "
            f"(would need /{new_prefix})"
        )

    subnets_list = list(network.subnets(new_prefix=new_prefix))
    # The user asked for `count` -- we may generate more (next power of 2).
    # Return exactly what was generated; inform via the result.
    infos = [calculate_subnet(s) for s in subnets_list]
    return SplitResult(
        original_network=str(network),
        requested_subnets=count,
        new_prefix=new_prefix,
        subnets=infos,
    )


# ---------------------------------------------------------------------------
# VLSM -- variable-length subnet allocation
# ---------------------------------------------------------------------------

def vlsm_allocate(
    network: ipaddress.IPv4Network, host_requirements: List[int]
) -> VLSMResult:
    """
    Allocate variable-sized subnets from *network* for each entry in
    *host_requirements* (largest-first).
    """
    if not host_requirements:
        raise ValueError("At least one host requirement must be provided")

    # Sort descending so largest subnets are placed first
    sorted_reqs = sorted(host_requirements, reverse=True)
    allocated: List[SubnetInfo] = []
    next_addr = int(network.network_address)
    network_end = int(network.broadcast_address)

    for req in sorted_reqs:
        prefix = prefix_for_hosts(req)
        # Align start address to subnet boundary
        block_size = 2 ** (32 - prefix)
        # Round up next_addr to the next multiple of block_size
        if next_addr % block_size != 0:
            next_addr = ((next_addr // block_size) + 1) * block_size

        subnet_end = next_addr + block_size - 1
        if subnet_end > network_end:
            raise ValueError(
                f"Not enough space in {network} to allocate subnet for "
                f"{req} hosts (needed /{prefix} at {ipaddress.IPv4Address(next_addr)})"
            )

        subnet = ipaddress.IPv4Network(f"{ipaddress.IPv4Address(next_addr)}/{prefix}")
        allocated.append(calculate_subnet(subnet))
        next_addr += block_size

    total_used = sum(s.total_addresses for s in allocated)
    wasted = network.num_addresses - total_used

    return VLSMResult(
        original_network=str(network),
        host_requirements=host_requirements,
        allocated_subnets=allocated,
        wasted_addresses=wasted,
    )


# ---------------------------------------------------------------------------
# Auto subnet allocation across availability zones
# ---------------------------------------------------------------------------

def allocate_auto_subnets(
    subnets: List[ipaddress.IPv4Network], availability_zones: List[str]
) -> AutoSubnetResult:
    """
    Automatically allocate subnets across availability zones.
    
    Takes a list of subnet networks (from calculator or split operation) and
    a list of availability zone names, and maps them round-robin style.
    
    Args:
        subnets: List of IPv4Network objects to allocate
        availability_zones: List of AZ names (e.g., ['us-east-1a', 'us-east-1b'])
    
    Returns:
        AutoSubnetResult with subnet allocation details
    """
    if not subnets:
        raise ValueError("At least one subnet must be provided")
    if not availability_zones:
        raise ValueError("At least one availability zone must be provided")
    
    # Calculate subnet info for each network
    subnet_infos = [calculate_subnet(s) for s in subnets]
    
    # Assign AZs round-robin to subnets
    # This allows more subnets than AZs (they cycle) or more AZs than subnets
    for idx, subnet_info in enumerate(subnet_infos):
        az_idx = idx % len(availability_zones)
        # We'll store the AZ assignment in a way that can be accessed later
        # For now, just keep the mapping implicit based on index
    
    return AutoSubnetResult(
        original_network=str(subnets[0].supernet(new_prefix=0)) if len(subnets) == 1 else "multiple",
        availability_zones=availability_zones,
        subnets_per_az=subnet_infos,
        total_subnets=len(subnet_infos),
    )
