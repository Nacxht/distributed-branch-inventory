"""Alat uji fault tolerance (butuh node hidup).

    python -m src.uji_fault delay <node> <detik>   # sengaja lambatkan node (0 = normal)
    python -m src.uji_fault baca <node> <kode>     # RPC get_stok dengan timeout+retry
    python -m src.uji_fault status                 # status heartbeat via API Node 1
"""
import json
import sys

import requests

from src.common.rpc_client import panggil_rpc

KLIEN = "Klien"

if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "delay":
        panggil_rpc(KLIEN, int(a[1]), "atur_delay", float(a[2]), retry=False)
    elif len(a) == 3 and a[0] == "baca":
        panggil_rpc(KLIEN, int(a[1]), "get_stok", a[2])
    elif a == ["status"]:
        r = requests.get("http://127.0.0.1:8001/status", timeout=15)
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    else:
        print(__doc__)
