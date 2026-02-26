"""
subnetcalc - IPv4 subnet calculation library.

Provides data models, calculation functions, and output formatting for
subnet info, FLSM splitting, and VLSM allocation.
"""

from .calculator import (
    allocate_auto_subnets,
    calculate_subnet,
    parse_network,
    prefix_for_hosts,
    split_network,
    vlsm_allocate,
)
from .formatter import format_split_result, format_subnet_info, format_vlsm_result
from .models import AutoSubnetResult, SplitResult, SubnetInfo, VLSMResult

__all__ = [
    # Models
    "SubnetInfo",
    "SplitResult",
    "VLSMResult",
    "AutoSubnetResult",
    # Calculation
    "calculate_subnet",
    "parse_network",
    "prefix_for_hosts",
    "split_network",
    "vlsm_allocate",
    "allocate_auto_subnets",
    # Formatting
    "format_subnet_info",
    "format_split_result",
    "format_vlsm_result",
]
