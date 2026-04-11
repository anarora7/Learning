# Learning

## VLAN Provisioning Script

This repository includes `vlan_provision.py`, a Python script that automates VLAN provisioning on Cisco Catalyst switches using Netmiko.

### What it does

- Connects to a Cisco IOS switch over SSH
- Creates a VLAN and assigns a VLAN name
- Configures the SVI interface with an IP address and subnet mask
- Adds a DHCP helper address
- Verifies both the VLAN and SVI configuration after deployment

### Requirements

- Python 3
- `netmiko`
- Network reachability to the target switch
- Valid switch credentials with configuration privileges

### Install dependencies

```bash
pip install netmiko
```

### Example usage

```bash
python vlan_provision.py \
  --host 192.168.1.10 \
  --username admin \
  --password yourpassword \
  --vlan_id 120 \
  --vlan_name Users_VLAN \
  --ip_address 10.120.0.1 \
  --subnet_mask 255.255.255.0 \
  --dhcp_helper 10.10.10.10
```

### Parameters

- `--host`: Switch hostname or IP address
- `--username`: SSH username
- `--password`: SSH password
- `--vlan_id`: VLAN ID from 1 to 4094
- `--vlan_name`: Name to assign to the VLAN
- `--ip_address`: IP address for the SVI
- `--subnet_mask`: Subnet mask for the SVI
- `--dhcp_helper`: DHCP helper address

### Notes

- The script validates VLAN ID, IPv4 addresses, subnet mask, and VLAN name before connecting.
- Verification checks both the VLAN definition and the SVI operational status.
- For better security, avoid hardcoding credentials in scripts or shell history when possible.
