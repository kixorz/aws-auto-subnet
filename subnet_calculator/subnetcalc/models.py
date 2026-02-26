"""Data structures for subnet calculation results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class SubnetInfo:
    """All computed properties for a single IPv4 subnet."""

    network_address: str
    broadcast_address: str
    first_usable_host: str
    last_usable_host: str
    subnet_mask: str
    wildcard_mask: str
    cidr_notation: str
    prefix_length: int
    total_addresses: int
    usable_hosts: int
    ip_class: str
    is_private: bool
    binary_ip: str
    binary_mask: str


@dataclass
class SplitResult:
    """Result of an FLSM split operation."""

    original_network: str
    requested_subnets: int
    new_prefix: int
    subnets: List[SubnetInfo]


@dataclass
class VLSMResult:
    """Result of a VLSM allocation."""

    original_network: str
    host_requirements: List[int]
    allocated_subnets: List[SubnetInfo]
    wasted_addresses: int


@dataclass
class AutoSubnetResult:
    """Result of an auto-subnet allocation."""

    original_network: str
    availability_zones: List[str]
    subnets_per_az: List[SubnetInfo]
    total_subnets: int
