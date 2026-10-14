"""LAPISAN 2a - RPC (xmlrpc).

[PERBEDAAN RPC vs RMI]
RPC: yang dipanggil adalah FUNGSI berdasarkan NAMA. Klien tidak memegang
     referensi objek; tidak ada stub berstate. Cukup nama fungsi + parameter,
     lalu menerima nilai kembalian.
RMI: lihat rmi_objects.py - klien memegang PROXY/STUB ke OBJEK remote yang
     punya state sendiri.
"""
import threading
import time
from socketserver import ThreadingMixIn
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

from . import logger
from .core import StokError, StokStore


class _ThreadedXMLRPCServer(ThreadingMixIn, SimpleXMLRPCServer):
    daemon_threads = True
    allow_reuse_address = True


_delay = {}   # node_id -> detik. FAULT INJECTION: delay buatan untuk demo timeout


def _bungkus(node_id, nama, fungsi):
    """Ubah exception jadi respons terstruktur supaya server tidak crash."""
    def _fn(*args):
        if _delay.get(node_id):
            time.sleep(_delay[node_id])
        try:
            hasil = {"ok": True, "data": fungsi(*args)}
        except StokError as e:
            hasil = {"ok": False, "error": str(e)}
        logger.diterima(node_id, "RPC", nama, args, hasil)
        return hasil
    return _fn


def jalankan_rpc(node_id: int, store: StokStore, host: str, port: int):
    server = _ThreadedXMLRPCServer((host, port), SimpleXMLRPCRequestHandler,
                                   logRequests=False, allow_none=True)
    fungsi = {
        "tambah_barang": store.tambah_barang,
        "ubah_stok": store.ubah_stok,
        "hapus_barang": store.hapus_barang,
        "get_stok": store.get_stok,
        "hitung_total": store.hitung_total,
        "daftar": store.daftar,
    }
    for nama, f in fungsi.items():
        server.register_function(_bungkus(node_id, nama, f), nama)
    # ping tanpa log berisik: dipakai heartbeat (ikut kena delay buatan)
    def _ping():
        if _delay.get(node_id):
            time.sleep(_delay[node_id])
        return "pong"
    server.register_function(_ping, "ping")

    def _atur_delay(detik):
        _delay[node_id] = float(detik)
        logger.info(node_id, f"FAULT INJECTION: delay buatan {float(detik):g} detik "
                             f"pada semua layanan RPC node ini")
        return {"ok": True, "data": {"delay": float(detik)}}
    server.register_function(_atur_delay, "atur_delay")

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info(node_id, f"RPC siap di {host}:{port}")
    return server
