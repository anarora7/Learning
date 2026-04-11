#!/usr/bin/env python3
"""
Python script to automate VLAN provisioning on Cisco Catalyst switches using Netmiko.

This script connects to a Cisco switch via SSH, creates a VLAN, configures the SVI
interface with an IP address and subnet mask, and sets a DHCP helper address.
"""

import argparse
import ipaddress
import re
import sys

from netmiko import (
    ConnectHandler,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


def validate_vlan_id(vlan_id):
    """Validate VLAN ID is in the range 1-4094."""
    if not (1 <= vlan_id <= 4094):
        raise ValueError("VLAN ID must be between 1 and 4094.")


def validate_ip_address(ip_str):
    """Validate IPv4 address format."""
    try:
        return str(ipaddress.IPv4Address(ip_str))
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"Invalid IP address: {ip_str}") from exc


def validate_subnet_mask(mask_str):
    """Validate dotted-decimal subnet mask format."""
    try:
        network = ipaddress.IPv4Network(f"0.0.0.0/{mask_str}")
    except ValueError as exc:
        raise ValueError(f"Invalid subnet mask: {mask_str}") from exc

    if str(network.netmask) != mask_str:
        raise ValueError(f"Invalid subnet mask: {mask_str}")

    return mask_str


def validate_vlan_name(vlan_name):
    """Validate VLAN name is present and safe for CLI usage."""
    clean_name = vlan_name.strip()
    if not clean_name:
        raise ValueError("VLAN name cannot be empty.")
    if len(clean_name) > 32:
        raise ValueError("VLAN name must be 32 characters or fewer.")
    return clean_name


def build_config_commands(vlan_id, vlan_name, ip_address, subnet_mask, dhcp_helper):
    """Build the list of configuration commands for VLAN and SVI."""
    return [
        f"vlan {vlan_id}",
        f"name {vlan_name}",
        "exit",
        f"interface vlan {vlan_id}",
        f"ip address {ip_address} {subnet_mask}",
        "no shutdown",
        f"ip helper-address {dhcp_helper}",
        "exit",
    ]


def verify_vlan_config(net_connect, vlan_id, vlan_name):
    """Verify VLAN creation by checking 'show vlan id <vlan_id>' output."""
    output = net_connect.send_command(f"show vlan id {vlan_id}")
    vlan_present = re.search(rf"\b{vlan_id}\b", output) is not None
    name_present = vlan_name.lower() in output.lower()
    return vlan_present and name_present


def verify_svi_config(net_connect, vlan_id, ip_address, subnet_mask, dhcp_helper):
    """Verify SVI interface config and operational state."""
    running_output = net_connect.send_command(f"show running-config interface vlan {vlan_id}")
    brief_output = net_connect.send_command("show ip interface brief")

    expected_lines = [
        f"interface Vlan{vlan_id}".lower(),
        f"ip address {ip_address} {subnet_mask}".lower(),
        "no shutdown",
        f"ip helper-address {dhcp_helper}".lower(),
    ]

    running_ok = all(line in running_output.lower() for line in expected_lines)

    brief_pattern = re.compile(
        rf"^Vlan{vlan_id}\s+{re.escape(ip_address)}\s+\S+\s+\S+\s+up\s+up$",
        re.IGNORECASE | re.MULTILINE,
    )
    brief_ok = brief_pattern.search(brief_output) is not None

    return running_ok and brief_ok


def main():
    parser = argparse.ArgumentParser(
        description="Automate VLAN provisioning on Cisco Catalyst switches."
    )
    parser.add_argument("--host", required=True, help="Switch IP address or hostname")
    parser.add_argument("--username", required=True, help="SSH username")
    parser.add_argument("--password", required=True, help="SSH password")
    parser.add_argument("--vlan_id", type=int, required=True, help="VLAN ID (1-4094)")
    parser.add_argument("--vlan_name", required=True, help="VLAN name")
    parser.add_argument("--ip_address", required=True, help="SVI IP address")
    parser.add_argument("--subnet_mask", required=True, help="SVI subnet mask")
    parser.add_argument("--dhcp_helper", required=True, help="DHCP helper address")

    args = parser.parse_args()

    try:
        vlan_id = args.vlan_id
        vlan_name = validate_vlan_name(args.vlan_name)
        ip_address = validate_ip_address(args.ip_address)
        subnet_mask = validate_subnet_mask(args.subnet_mask)
        dhcp_helper = validate_ip_address(args.dhcp_helper)
        validate_vlan_id(vlan_id)
    except ValueError as exc:
        print(f"Input validation error: {exc}")
        sys.exit(1)

    device = {
        "device_type": "cisco_ios",
        "host": args.host,
        "username": args.username,
        "password": args.password,
        "fast_cli": False,
    }

    try:
        print(f"Connecting to {args.host}...")
        net_connect = ConnectHandler(**device)
    except NetmikoTimeoutException:
        print(f"Connection timed out to device {args.host}.")
        sys.exit(2)
    except NetmikoAuthenticationException:
        print(f"Authentication failed for device {args.host}.")
        sys.exit(3)
    except Exception as exc:
        print(f"Failed to connect to device {args.host}: {exc}")
        sys.exit(4)

    config_commands = build_config_commands(
        vlan_id, vlan_name, ip_address, subnet_mask, dhcp_helper
    )

    try:
        print("Sending configuration commands...")
        output = net_connect.send_config_set(config_commands)
        print(output)
    except Exception as exc:
        print(f"Failed to send configuration: {exc}")
        net_connect.disconnect()
        sys.exit(5)

    print("Verifying VLAN configuration...")
    if not verify_vlan_config(net_connect, vlan_id, vlan_name):
        print(
            f"Verification failed: VLAN {vlan_id} with name '{vlan_name}' not found."
        )
        net_connect.disconnect()
        sys.exit(6)

    print("Verifying SVI interface configuration...")
    if not verify_svi_config(
        net_connect, vlan_id, ip_address, subnet_mask, dhcp_helper
    ):
        print(f"Verification failed: SVI interface Vlan{vlan_id} not configured correctly.")
        net_connect.disconnect()
        sys.exit(7)

    print(f"VLAN {vlan_id} and SVI configured successfully on {args.host}.")
    net_connect.disconnect()


if __name__ == "__main__":
    main()
