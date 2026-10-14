"""DETEKSI KEGAGALAN: heartbeat (ping RPC) berkala ke semua node lain.

Node dinyatakan MATI setelah HEARTBEAT_GAGAL ping gagal berturut-turut
(timeout atau tidak terhubung), dan HIDUP kembali begitu satu ping berhasil.
"""
import threading
import time

from . import config, logger
from .rpc_client import panggil_rpc

_aktif = None


class Detektor:
    def __init__(self, node_id):
        self.node_id = node_id
        self._mutex = threading.Lock()
        self._s = {n: {"hidup": True, "gagal": 0, "terakhir": None}
                   for n in config.NODES if n != node_id}

    def mulai(self):
        for n in self._s:
            threading.Thread(target=self._pantau, args=(n,), daemon=True).start()
        logger.info(self.node_id, f"HEARTBEAT aktif: ping tiap {config.heartbeat_interval():g}s, "
                                  f"mati setelah {config.heartbeat_gagal()} gagal berturut-turut")

    def _pantau(self, n):
        batas = config.heartbeat_gagal()
        while True:
            r = panggil_rpc(self.node_id, n, "ping", retry=False, senyap=True)
            ok = (r == "pong")
            with self._mutex:
                s = self._s[n]
                if ok:
                    if not s["hidup"]:
                        logger.info(self.node_id, f"HEARTBEAT: Node {n} HIDUP kembali")
                    s.update(hidup=True, gagal=0, terakhir=time.time())
                else:
                    s["gagal"] += 1
                    sebab = r.get("jenis_error", "?") if isinstance(r, dict) else "?"
                    if s["hidup"] and s["gagal"] < batas:
                        logger.info(self.node_id, f"HEARTBEAT: ping Node {n} gagal "
                                                  f"({s['gagal']}/{batas}, {sebab})")
                    elif s["hidup"] and s["gagal"] >= batas:
                        s["hidup"] = False
                        logger.info(self.node_id, f"HEARTBEAT: Node {n} dinyatakan MATI "
                                                  f"({batas} ping gagal berturut-turut, {sebab})")
            time.sleep(config.heartbeat_interval())

    def ringkas(self):
        with self._mutex:
            return {n: {"hidup": s["hidup"], "gagal_beruntun": s["gagal"]}
                    for n, s in self._s.items()}


def mulai_heartbeat(node_id):
    global _aktif
    _aktif = Detektor(node_id)
    _aktif.mulai()
    return _aktif


def detektor():
    return _aktif
