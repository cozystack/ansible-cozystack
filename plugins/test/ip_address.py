# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Cozystack Contributors
# Apache License 2.0 (see LICENSE file in the repository root)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = """
    name: is_ip_address
    author: Cozystack Contributors
    version_added: "1.2.3"
    short_description: Test whether a string is a valid IPv4 or IPv6 address
    description:
      - Returns True if the input is a valid IPv4 or IPv6 address.
      - Uses the Python standard library C(ipaddress) module, so no external
        dependencies (such as C(netaddr)) are required.
    options:
      _input:
        description: The string to test.
        type: str
        required: true
"""

EXAMPLES = """
- name: Validate an IP address
  ansible.builtin.assert:
    that:
      - "'10.0.0.1' is cozystack.installer.is_ip_address"
      - "'2001:db8::1' is cozystack.installer.is_ip_address"
      - "'node1.example.com' is not cozystack.installer.is_ip_address"
"""

RETURN = """
  _value:
    description: True if input is a valid IP address, otherwise False.
    type: bool
"""

from ipaddress import ip_address


def is_ip_address(value):
    if not isinstance(value, str):
        return False
    try:
        ip_address(value)
    except (ValueError, TypeError):
        return False
    return True


class TestModule:
    def tests(self):
        return {"is_ip_address": is_ip_address}
