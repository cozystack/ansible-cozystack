# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Cozystack Contributors
# Apache License 2.0 (see LICENSE file in the repository root)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible_collections.cozystack.installer.plugins.test.ip_address import (
    is_ip_address,
)


def test_valid_ipv4():
    assert is_ip_address("10.0.0.1") is True
    assert is_ip_address("192.168.1.1") is True
    assert is_ip_address("0.0.0.0") is True
    assert is_ip_address("255.255.255.255") is True


def test_valid_ipv6():
    assert is_ip_address("2001:db8::1") is True
    assert is_ip_address("::1") is True
    assert is_ip_address("fe80::1") is True
    assert is_ip_address("2001:0db8:85a3:0000:0000:8a2e:0370:7334") is True


def test_invalid_hostname():
    assert is_ip_address("node1.example.com") is False
    assert is_ip_address("foo") is False
    assert is_ip_address("localhost") is False


def test_invalid_format():
    assert is_ip_address("999.999.999.999") is False
    assert is_ip_address("10.0.0.1.2") is False
    assert is_ip_address("10.0.0") is False
    assert is_ip_address("") is False


def test_non_string_input():
    # The plugin should not raise on None; return False instead.
    assert is_ip_address(None) is False


def test_rejects_non_string_types():
    # ipaddress.ip_address() silently accepts integers and booleans
    # (treating them as 32-bit address values), but the plugin
    # contract declares type: str — enforce it explicitly.
    assert is_ip_address(42) is False
    assert is_ip_address(True) is False
    assert is_ip_address(False) is False
    assert is_ip_address(b"10.0.0.1") is False
    assert is_ip_address([]) is False
