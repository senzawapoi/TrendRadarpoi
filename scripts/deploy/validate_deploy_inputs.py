"""Validate literal deployment inputs before constructing SSH commands."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import sys
from collections.abc import Mapping


def validate_release_id(value: str) -> None:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", value)
        or ".." in value
        or value.endswith((".", "-"))
    ):
        raise ValueError("invalid RELEASE_ID")


def validate_deploy_inputs(values: Mapping[str, str]) -> int:
    validate_release_id(values.get("RELEASE_ID", ""))
    path = values.get("DEPLOY_PATH", "")
    if (
        not re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
        or any(part in {"", ".", ".."} for part in path.split("/")[1:])
    ):
        raise ValueError("invalid DEPLOY_PATH")
    user = values.get("DEPLOY_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}", user):
        raise ValueError("invalid DEPLOY_USER")
    host = values.get("DEPLOY_HOST", "")
    # DNS names and IPv4 literals only; no SSH aliases, options, URI or IPv6 syntax.
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    if len(host) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*", host):
        raise ValueError("invalid DEPLOY_HOST")
    if re.fullmatch(r"[0-9.]+", host):
        try:
            ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError:
            raise ValueError("invalid DEPLOY_HOST") from None
    port = values.get("DEPLOY_PORT", "") or "22"
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
        raise ValueError("invalid DEPLOY_PORT")
    return int(port)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.release_only:
            validate_release_id(os.environ.get("RELEASE_ID", ""))
        else:
            print(validate_deploy_inputs(os.environ))
    except ValueError as error:
        # Report field names only; input values may be GitHub secrets.
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
