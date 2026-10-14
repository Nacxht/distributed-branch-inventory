"""Klien RPC: timeout + retry (lihat resilience.py) + log."""
import http.client
import socket
import xmlrpc.client

from . import config
from .resilience import dengan_retry


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        return http.client.HTTPConnection(host, timeout=self._timeout)


def _sekali(tujuan, method, params):
    proxy = xmlrpc.client.ServerProxy(
        config.rpc_url(tujuan),
        transport=_TimeoutTransport(config.rpc_timeout()),
        allow_none=True,
    )
    try:
        return getattr(proxy, method)(*params)
    except (socket.timeout, TimeoutError):
        return {"ok": False, "jenis_error": "timeout", "error": f"timeout ke Node {tujuan}"}
    except (ConnectionError, OSError):
        return {"ok": False, "jenis_error": "tidak_terhubung",
                "error": f"Node {tujuan} tidak dapat dihubungi"}


def panggil_rpc(pemanggil, tujuan: int, method: str, *params, retry=True, senyap=False):
    """Panggil fungsi RPC di node lain seolah fungsi lokal. Return dict respons."""
    return dengan_retry(pemanggil, tujuan, "RPC", method, params, method,
                        lambda: _sekali(tujuan, method, params), retry, senyap)
