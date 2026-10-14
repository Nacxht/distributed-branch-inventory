"""LAPISAN 2b - RMI (Pyro5): OBJEK remote yang punya state.

[PERBEDAAN RPC vs RMI]
RPC (rpc_server.py): fungsi tanpa state, dipanggil per nama.
RMI (file ini)     : ada INTERFACE (method yang di-@expose), OBJEK remote
                     (instance kelas) yang hidup di server dan menyimpan
                     state, dan klien memanggilnya lewat PROXY/STUB.

Objek di sini:
  - LockManager (Node 1/Pusat): state = daftar lock aktif (mutual exclusion).
  - Cabang (Node 2,3)         : state = jumlah transfer yang sudah dilakukan;
                                transfer_stok memakai RMI (lock) + RPC (ubah stok).
  - Replika (Node 4)          : state = salinan data tiap node sumber + nomor
                                versinya (sinkronisasi/replikasi data).
"""
import json
import os
import threading
import time

import Pyro5.api

from . import config, logger
from .core import StokError, StokStore
from .rmi_client import panggil_rmi
from .rpc_client import panggil_rpc

PUSAT = 1
REPLIKA = 4   # juga menjadi lock manager CADANGAN (failover)
LEASE_DEFAULT = 10  # detik: lock otomatis kadaluarsa (anti lock yatim)


@Pyro5.api.expose
class LockManager:
    """Lock terpusat per kode barang, dengan lease."""

    def __init__(self, node_id: int):
        self._node_id = node_id
        self._locks = {}          # kode -> {"pemilik", "kadaluarsa"}
        self._mutex = threading.Lock()

    def acquire(self, kode, pemilik, lease=LEASE_DEFAULT):
        now = time.time()
        with self._mutex:
            cur = self._locks.get(kode)
            if cur and cur["kadaluarsa"] > now and cur["pemilik"] != pemilik:
                hasil = {"ok": False, "dikunci": True, "pemilik": cur["pemilik"],
                         "error": f"{kode} sedang dikunci Node {cur['pemilik']}"}
            else:
                self._locks[kode] = {"pemilik": pemilik, "kadaluarsa": now + lease}
                hasil = {"ok": True, "data": {"kode": kode, "pemilik": pemilik, "lease": lease}}
        logger.diterima(self._node_id, "RMI", "LockManager.acquire", (kode, pemilik), hasil)
        return hasil

    def release(self, kode, pemilik):
        with self._mutex:
            cur = self._locks.get(kode)
            if cur and cur["pemilik"] == pemilik:
                del self._locks[kode]
                hasil = {"ok": True, "data": {"kode": kode, "dilepas": True}}
            else:
                hasil = {"ok": False, "error": f"{kode} tidak dikunci oleh Node {pemilik}"}
        logger.diterima(self._node_id, "RMI", "LockManager.release", (kode, pemilik), hasil)
        return hasil

    def status(self):
        now = time.time()
        with self._mutex:
            aktif = {k: {"pemilik": v["pemilik"], "sisa_detik": round(v["kadaluarsa"] - now, 1)}
                     for k, v in self._locks.items() if v["kadaluarsa"] > now}
        return {"ok": True, "data": aktif}


@Pyro5.api.expose
class Cabang:
    """Objek cabang: stateful (menghitung transfer) dan mengoordinasi transfer."""

    def __init__(self, node_id: int, store: StokStore):
        self._node_id = node_id
        self._store = store
        self._jumlah_transfer = 0

    def info(self):
        hasil = {"ok": True, "data": {"node": self._node_id,
                                      "jumlah_transfer": self._jumlah_transfer,
                                      **self._store.hitung_total()}}
        logger.diterima(self._node_id, "RMI", "Cabang.info", (), hasil)
        return hasil

    def transfer_stok(self, kode, jumlah, tujuan, simulasi_delay=0):
        """Pindahkan stok dari cabang ini ke cabang `tujuan`.
        RMI: minta/lepas lock ke LockManager di Pusat.
        RPC: ubah stok di cabang tujuan."""
        n = self._node_id
        hasil = self._transfer(n, kode, jumlah, tujuan, simulasi_delay)
        logger.diterima(n, "RMI", "Cabang.transfer_stok", (kode, jumlah, tujuan), hasil)
        return hasil

    # ---- internal ----
    def _transfer(self, n, kode, jumlah, tujuan, delay):
        if jumlah <= 0:
            return {"ok": False, "error": "jumlah harus > 0"}
        if tujuan == n or tujuan not in (2, 3):
            return {"ok": False, "error": "tujuan harus cabang lain (2 atau 3)"}

        mgr, alasan = self._ambil_lock(kode)
        if mgr is None:
            if alasan == "tidak_tersedia":
                return {"ok": False, "sebab": "tidak_terhubung",
                        "error": f"lock manager (Node {PUSAT} dan cadangan Node {REPLIKA}) tidak tersedia"}
            return {"ok": False, "error": f"gagal mendapat lock {kode}: menunggu terlalu lama"}
        try:
            if delay:
                logger.info(n, f"memproses transfer {kode} (simulasi {delay}s), lock dipegang")
                time.sleep(delay)
            try:
                self._store.ubah_stok(kode, -jumlah)
            except StokError as e:
                return {"ok": False, "error": str(e)}

            r = panggil_rpc(n, tujuan, "ubah_stok", kode, jumlah)
            if not r["ok"] and "tidak ditemukan" in r.get("error", ""):
                nama = self._store.barang[kode]["nama"]
                r = panggil_rpc(n, tujuan, "tambah_barang", kode, nama, jumlah)
            if not r["ok"]:
                self._store.ubah_stok(kode, jumlah)  # rollback stok lokal
                logger.info(n, f"transfer dibatalkan, stok {kode} dikembalikan (rollback)")
                return {"ok": False, "rollback": True, "sebab": r.get("jenis_error"),
                        "error": f"transfer dibatalkan: {r['error']}"}

            self._jumlah_transfer += 1
            return {"ok": True, "data": {"kode": kode, "jumlah": jumlah,
                                         "dari": n, "ke": tujuan,
                                         "stok_lokal": self._store.barang[kode]["stok"],
                                         "lock_manager": mgr}}
        finally:
            panggil_rmi(n, mgr, "lockmanager", "release", kode, n)

    def _ambil_lock(self, kode, tunggu=12.0, jeda=0.5):
        """Minta lock ke Pusat; bila Pusat tidak tersedia, FAILOVER ke cadangan di Node 4.
        Return (node_manager, alasan_gagal). tunggu > lease (10s) supaya lock
        milik node yang mati sempat kadaluarsa."""
        n = self._node_id
        for idx, mgr in enumerate((PUSAT, REPLIKA)):
            mulai = time.time()
            while True:
                r = panggil_rmi(n, mgr, "lockmanager", "acquire", kode, n)
                if r.get("ok"):
                    return mgr, None
                if not r.get("dikunci"):               # manager tidak tersedia
                    if idx == 0:
                        logger.info(n, f"FAILOVER: lock manager Node {mgr} tidak tersedia "
                                       f"({r.get('error')}), beralih ke cadangan Node {REPLIKA}")
                    break
                if time.time() - mulai > tunggu:
                    logger.info(n, f"menyerah menunggu lock {kode}")
                    return None, "menyerah"
                logger.info(n, f"lock {kode} dipegang Node {r['pemilik']}, menunggu...")
                time.sleep(jeda)
        return None, "tidak_tersedia"


@Pyro5.api.expose
class Replika:
    """Menyimpan salinan data tiap node sumber. Sinkronisasi berbasis NOMOR VERSI:
    salinan baru hanya diterapkan bila versinya lebih tinggi (kiriman usang/
    terlambat diabaikan), sehingga urutan kedatangan tidak merusak konsistensi."""

    def __init__(self, node_id: int, data_dir: str):
        self._node_id = node_id
        self._mutex = threading.Lock()
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, f"replika_node{node_id}.json")
        self._salinan = {}   # "sumber" -> {"versi": int, "barang": dict}
        if os.path.exists(self._path):
            with open(self._path, encoding="utf-8") as f:
                self._salinan = json.load(f)

    def _simpan(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._salinan, f, indent=2)

    def _terapkan(self, sumber, versi, barang):
        k = str(sumber)
        with self._mutex:
            cur = self._salinan.get(k, {"versi": -1})
            if versi > cur["versi"]:
                self._salinan[k] = {"versi": versi, "barang": barang}
                self._simpan()
                hasil = "diterapkan"
            elif versi == cur["versi"]:
                hasil = "sudah_sama"
            else:
                hasil = "diabaikan_usang"
            return {"sumber": sumber, "hasil": hasil,
                    "versi_replika": self._salinan[k]["versi"]}

    def terima_replikasi(self, sumber, versi, barang):
        hasil = {"ok": True, "data": self._terapkan(sumber, versi, barang)}
        logger.diterima(self._node_id, "RMI", "Replika.terima_replikasi",
                        (sumber, f"v{versi}", f"{len(barang)} barang"), hasil)
        return hasil

    def ambil_data_tertinggal(self, sumber, versi_lokal):
        """Recovery: node sumber yang kembali hidup menanyakan data yang tertinggal."""
        cur = self._salinan.get(str(sumber))
        if cur and cur["versi"] > versi_lokal:
            data = {"lebih_baru": True, "versi": cur["versi"], "barang": cur["barang"]}
        else:
            data = {"lebih_baru": False, "versi": cur["versi"] if cur else None}
        hasil = {"ok": True, "data": data}
        logger.diterima(self._node_id, "RMI", "Replika.ambil_data_tertinggal",
                        (sumber, f"v{versi_lokal}"), {"lebih_baru": data["lebih_baru"],
                                                      "versi": data["versi"]})
        return hasil

    def salinan(self, sumber):
        cur = self._salinan.get(str(sumber))
        if not cur:
            return {"ok": False, "error": f"belum ada salinan dari Node {sumber}"}
        return {"ok": True, "data": cur}

    def status(self):
        return {"ok": True, "data": {k: {"versi": v["versi"], "jumlah_barang": len(v["barang"])}
                                     for k, v in self._salinan.items()}}

    def sinkron_ulang(self):
        """PULL: Replika menarik data terbaru dari Node 1-3 (dipakai saat Node 4
        baru hidup kembali dan tertinggal dari perubahan yang terjadi selagi mati)."""
        n = self._node_id
        logger.info(n, "SINKRON (pull) mulai: menarik data dari Node 1, 2, 3")
        ringkas = {}
        for sumber in (1, 2, 3):
            r = panggil_rpc(n, sumber, "daftar", retry=False)
            if not r.get("ok"):
                ringkas[f"node{sumber}"] = "tidak_dapat_dihubungi"
                continue
            d = r["data"]
            ringkas[f"node{sumber}"] = self._terapkan(sumber, d["versi_global"], d["barang"])["hasil"]
        logger.info(n, f"SINKRON (pull) selesai: {ringkas}")
        return {"ok": True, "data": ringkas}


def jalankan_rmi(node_id: int, store: StokStore, host: str, port: int):
    peran = config.NODES[node_id]["peran"]
    daemon = Pyro5.api.Daemon(host=host, port=port)
    objek = None
    if peran == "pusat":
        daemon.register(LockManager(node_id), objectId="lockmanager")
        logger.info(node_id, f"RMI siap di {host}:{port} (objek: lockmanager)")
    elif peran == "cabang":
        objek = Cabang(node_id, store)
        daemon.register(objek, objectId="cabang")
        logger.info(node_id, f"RMI siap di {host}:{port} (objek: cabang)")
    else:
        objek = Replika(node_id, store.data_dir)
        daemon.register(objek, objectId="replika")
        daemon.register(LockManager(node_id), objectId="lockmanager")  # cadangan
        logger.info(node_id, f"RMI siap di {host}:{port} (objek: replika, lockmanager cadangan)")
    threading.Thread(target=daemon.requestLoop, daemon=True).start()
    return daemon, objek
