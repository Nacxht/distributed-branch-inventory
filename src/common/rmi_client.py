"""Klien RMI (Pyro5): memegang PROXY/STUB ke objek remote di node lain.

[PERBEDAAN dengan rpc_client.py]
RPC : ServerProxy -> panggil FUNGSI per nama ("get_stok").
RMI : Proxy ke OBJEK ("lockmanager" / "cabang" / "replika") lalu panggil METHOD
      pada objek itu. Objek di sisi server menyimpan state sendiri.
Timeout + retry memakai mekanisme yang sama dengan RPC (resilience.py).
"""
import Pyro5.api
import Pyro5.errors

from . import config
from .resilience import dengan_retry


def _sekali(tujuan, objek, method, params, timeout):
    uri = config.rmi_uri(tujuan, objek)
    try:
        with Pyro5.api.Proxy(uri) as proxy:          # <- stub/proxy di sisi klien
            proxy._pyroTimeout = timeout or config.rpc_timeout()
            return getattr(proxy, method)(*params)   # <- method pada objek remote
    except Pyro5.errors.TimeoutError:
        return {"ok": False, "jenis_error": "timeout", "error": f"timeout ke Node {tujuan}"}
    except Pyro5.errors.CommunicationError:
        return {"ok": False, "jenis_error": "tidak_terhubung",
                "error": f"Node {tujuan} tidak dapat dihubungi"}


def panggil_rmi(pemanggil, tujuan: int, objek: str, method: str, *params,
                timeout: float = None, retry=True, senyap=False):
    """Panggil method pada objek remote. Return dict respons (tidak pernah raise)."""
    return dengan_retry(pemanggil, tujuan, "RMI", f"{objek}.{method}", params, method,
                        lambda: _sekali(tujuan, objek, method, params, timeout),
                        retry, senyap)
