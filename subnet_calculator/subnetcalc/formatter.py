"""Human-readable formatting for subnet calculation results."""

from __future__ import annotations

from .models import SplitResult, SubnetInfo, VLSMResult

_LABEL_WIDTH = 22


def _kv(label: str, value: str) -> str:
    return f"  {label:<{_LABEL_WIDTH}} {value}"


def format_subnet_info(info: SubnetInfo) -> str:
    """Return a human-readable block of subnet information."""
    private_str = "Private" if info.is_private else "Public"
    lines = [
        _kv("Network Address:", info.network_address),
        _kv("Broadcast Address:", info.broadcast_address),
        _kv("First Usable Host:", info.first_usable_host),
        _kv("Last Usable Host:", info.last_usable_host),
        _kv("Subnet Mask:", info.subnet_mask),
        _kv("Wildcard Mask:", info.wildcard_mask),
        _kv("CIDR Notation:", info.cidr_notation),
        _kv("Prefix Length:", f"/{info.prefix_length}"),
        _kv("Total Addresses:", str(info.total_addresses)),
        _kv("Usable Hosts:", str(info.usable_hosts)),
        _kv("IP Class:", info.ip_class),
        _kv("Private/Public:", private_str),
        _kv("Binary IP:", info.binary_ip),
        _kv("Binary Mask:", info.binary_mask),
    ]
    return "\n".join(lines)


def format_split_result(result: SplitResult) -> str:
    """Format an FLSM split result for the terminal."""
    header = (
        f"Splitting {result.original_network} into "
        f"{len(result.subnets)} subnets (/{result.new_prefix})\n"
        f"{'=' * 60}"
    )
    blocks = []
    for i, subnet in enumerate(result.subnets, 1):
        blocks.append(f"\n--- Subnet {i} ---\n{format_subnet_info(subnet)}")
    return header + "\n".join(blocks)


def format_vlsm_result(result: VLSMResult) -> str:
    """Format a VLSM allocation result for the terminal."""
    header = (
        f"VLSM allocation from {result.original_network}\n"
        f"Host requirements (sorted largest-first): "
        f"{sorted(result.host_requirements, reverse=True)}\n"
        f"{'=' * 60}"
    )
    blocks = []
    sorted_reqs = sorted(result.host_requirements, reverse=True)
    for i, (subnet, req) in enumerate(
        zip(result.allocated_subnets, sorted_reqs), 1
    ):
        blocks.append(
            f"\n--- Subnet {i} (need {req} hosts) ---\n"
            f"{format_subnet_info(subnet)}"
        )
    footer = f"\nWasted addresses: {result.wasted_addresses}"
    return header + "\n".join(blocks) + footer
