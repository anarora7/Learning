#!/usr/bin/env python3
"""
Automate VLAN provisioning on Cisco Catalyst switches using Netmiko.

The script can connect to a real device or run in dry-run mode to simulate
the generated commands and verification steps.
"""

import argparse
import ipaddress
import re
import sys
from dataclasses import dataclass

from netmiko import (
    ConnectHandler,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


EXIT_INVALID_INPUT = 1
EXIT_TIMEOUT = 2
EXIT_AUTH_FAILED = 3
EXIT_CONNECTION_FAILED = 4
EXIT_CONFIG_FAILED = 5
EXIT_VLAN_VERIFY_FAILED = 6
EXIT_SVI_VERIFY_FAILED = 7


@dataclass(frozen=True)
class VlanProvisionRequest:
    host: str
    username: str
    password: str
    vlan_id: int
    vlan_name: str
    ip_address: str
    subnet_mask: str
    dhcp_helper: str
    dry_run: bool = False

    @property
    def device_params(self):
        return {
            "device_type": "cisco_ios",
            "host": self.host,
            "username": self.username,
            "password": self.password,
            "fast_cli": False,
        }


class DryRunConnection:
    """Small simulator that mirrors the Netmiko methods this script uses."""

    def __init__(self, request):
        self.request = request

    def send_config_set(self, commands):
        print("Simulating send_config_set with commands:")
        for command in commands:
            print(f"  {command}")
        return "Configuration simulated successfully.\n"

    def send_command(self, command):
        print(f"Simulating send_command: {command}")

        if command == f"show vlan id {self.request.vlan_id}":
            return (
                "VLAN Name                             Status    Ports\n"
                "---- -------------------------------- --------- ----------------------------\n"
                f"{self.request.vlan_id:<4} {self.request.vlan_name:<32} active\n"
            )

        if command == f"show running-config interface vlan {self.request.vlan_id}":
            return (
                f"interface Vlan{self.request.vlan_id}\n"
                f" ip address {self.request.ip_address} {self.request.subnet_mask}\n"
                " no shutdown\n"
                f" ip helper-address {self.request.dhcp_helper}\n"
            )

        if command == "show ip interface brief":
            return (
                "Interface              IP-Address      OK? Method Status                Protocol\n"
                f"Vlan{self.request.vlan_id:<18}{self.request.ip_address:<16}"
                "YES manual up                    up\n"
            )

        return "Simulated command output.\n"

    def disconnect(self):
        return None


def parse_args(argv=None):
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
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Simulate device interaction without connecting to a switch",
    )
    return parser.parse_args(argv)


def validate_vlan_id(vlan_id):
    if not (1 <= vlan_id <= 4094):
        raise ValueError("VLAN ID must be between 1 and 4094.")
    return vlan_id


def validate_ip_address(ip_str):
    try:
        return str(ipaddress.IPv4Address(ip_str))
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"Invalid IP address: {ip_str}") from exc


def validate_subnet_mask(mask_str):
    try:
        network = ipaddress.IPv4Network(f"0.0.0.0/{mask_str}")
    except ValueError as exc:
        raise ValueError(f"Invalid subnet mask: {mask_str}") from exc

    if str(network.netmask) != mask_str:
        raise ValueError(f"Invalid subnet mask: {mask_str}")

    return mask_str


def validate_vlan_name(vlan_name):
    clean_name = vlan_name.strip()
    if not clean_name:
        raise ValueError("VLAN name cannot be empty.")
    if len(clean_name) > 32:
        raise ValueError("VLAN name must be 32 characters or fewer.")
    return clean_name


def build_request(args):
    return VlanProvisionRequest(
        host=args.host,
        username=args.username,
        password=args.password,
        vlan_id=validate_vlan_id(args.vlan_id),
        vlan_name=validate_vlan_name(args.vlan_name),
        ip_address=validate_ip_address(args.ip_address),
        subnet_mask=validate_subnet_mask(args.subnet_mask),
        dhcp_helper=validate_ip_address(args.dhcp_helper),
        dry_run=args.dry_run,
    )


def build_config_commands(request):
    return [
        f"vlan {request.vlan_id}",
        f"name {request.vlan_name}",
        "exit",
        f"interface vlan {request.vlan_id}",
        f"ip address {request.ip_address} {request.subnet_mask}",
        "no shutdown",
        f"ip helper-address {request.dhcp_helper}",
        "exit",
    ]


def verify_vlan_config(connection, request):
    output = connection.send_command(f"show vlan id {request.vlan_id}")
    vlan_present = re.search(rf"\b{request.vlan_id}\b", output) is not None
    name_present = request.vlan_name.lower() in output.lower()
    return vlan_present and name_present


def verify_svi_config(connection, request):
    running_output = connection.send_command(
        f"show running-config interface vlan {request.vlan_id}"
    )
    brief_output = connection.send_command("show ip interface brief")

    expected_lines = [
        f"interface Vlan{request.vlan_id}".lower(),
        f"ip address {request.ip_address} {request.subnet_mask}".lower(),
        "no shutdown",
        f"ip helper-address {request.dhcp_helper}".lower(),
    ]
    running_ok = all(line in running_output.lower() for line in expected_lines)

    brief_pattern = re.compile(
        rf"^Vlan{request.vlan_id}\s+{re.escape(request.ip_address)}\s+\S+\s+\S+\s+up\s+up$",
        re.IGNORECASE | re.MULTILINE,
    )
    brief_ok = brief_pattern.search(brief_output) is not None

    return running_ok and brief_ok


def connect_to_device(request):
    if request.dry_run:
        print("Running in DRY-RUN mode. No device connection will be made.")
        return DryRunConnection(request)

    try:
        print(f"Connecting to {request.host}...")
        return ConnectHandler(**request.device_params)
    except NetmikoTimeoutException:
        print(f"Connection timed out to device {request.host}.")
        sys.exit(EXIT_TIMEOUT)
    except NetmikoAuthenticationException:
        print(f"Authentication failed for device {request.host}.")
        sys.exit(EXIT_AUTH_FAILED)
    except Exception as exc:
        print(f"Failed to connect to device {request.host}: {exc}")
        sys.exit(EXIT_CONNECTION_FAILED)


def run_provisioning(request):
    connection = connect_to_device(request)

    try:
        print("Sending configuration commands...")
        output = connection.send_config_set(build_config_commands(request))
        print(output)

        print("Verifying VLAN configuration...")
        if not verify_vlan_config(connection, request):
            print(
                f"Verification failed: VLAN {request.vlan_id} "
                f"with name '{request.vlan_name}' not found."
            )
            sys.exit(EXIT_VLAN_VERIFY_FAILED)

        print("Verifying SVI interface configuration...")
        if not verify_svi_config(connection, request):
            print(
                f"Verification failed: SVI interface Vlan{request.vlan_id} "
                "not configured correctly."
            )
            sys.exit(EXIT_SVI_VERIFY_FAILED)

        print(
            f"VLAN {request.vlan_id} and SVI configured successfully on {request.host}."
        )
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Failed to send configuration: {exc}")
        sys.exit(EXIT_CONFIG_FAILED)
    finally:
        connection.disconnect()


def main(argv=None):
    try:
        request = build_request(parse_args(argv))
    except ValueError as exc:
        print(f"Input validation error: {exc}")
        sys.exit(EXIT_INVALID_INPUT)

    run_provisioning(request)


if __name__ == "__main__":
    main()
