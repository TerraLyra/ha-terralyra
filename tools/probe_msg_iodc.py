#!/usr/bin/env python3
"""Fetch one MSG-IODC List Product and print only bounded schema metadata.

Credentials are read from the LSA_SAF_USERNAME and LSA_SAF_PASSWORD
environment variables.  The downloaded HDF5 payload stays in memory, is never
written to disk, and dataset values are never read.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "terralyra"
    / "products"
    / "msg_iodc.py"
)
SPEC = importlib.util.spec_from_file_location("terralyra_msg_iodc_probe", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load the MSG-IODC schema module")
MSG_IODC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MSG_IODC)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> int:
    username = os.environ.get("LSA_SAF_USERNAME")
    password = os.environ.get("LSA_SAF_PASSWORD")
    if not username or not password:
        print(
            "Set LSA_SAF_USERNAME and LSA_SAF_PASSWORD in the process environment.",
            file=sys.stderr,
        )
        return 2

    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    opener = urllib.request.build_opener(_NoRedirect())
    headers = {
        "Authorization": f"Basic {token}",
        "User-Agent": "TerraLyra-MSG-IODC-schema-probe/1",
    }
    for filename, url in MSG_IODC.candidate_list_products(datetime.now(UTC)):
        request = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(request, timeout=30) as response:
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > MSG_IODC.MAX_DOWNLOAD_BYTES:
                    raise MSG_IODC.MsgIodcSchemaError(
                        "MSG-IODC response exceeds the probe size limit"
                    )
                payload = response.read(MSG_IODC.MAX_DOWNLOAD_BYTES + 1)
        except urllib.error.HTTPError as err:
            if err.code == 404:
                continue
            if err.code in (401, 403):
                print("LSA SAF credentials were rejected.", file=sys.stderr)
                return 3
            print(f"LSA SAF returned HTTP {err.code}.", file=sys.stderr)
            return 4
        except (TimeoutError, urllib.error.URLError) as err:
            print(f"LSA SAF request failed: {type(err).__name__}.", file=sys.stderr)
            return 4

        schema = MSG_IODC.inspect_list_product_schema(filename, payload)
        print(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    print("No MSG-IODC List Product was found in the bounded lookback.", file=sys.stderr)
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
