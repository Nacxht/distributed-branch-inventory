"""LAPISAN 3 - logika stok (satu-satunya sumber kebenaran).

RPC, RMI, dan REST API semuanya memanggil kelas ini. Tidak ada logika bisnis
di lapisan lain.
"""
import copy
import json
import os
import threading


class StokError(Exception):
    """Error bisnis (barang tidak ada, stok kurang, dll)."""


class StokStore:
    def __init__(self, node_id: int, data_dir: str = "data"):
        self.node_id = node_id
        self._lock = threading.RLock()
        self.data_dir = data_dir
        self.on_change = None   # callback replikasi: (node_id, versi, barang)
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, f"data_node{node_id}.json")
        self.versi_global = 0
        self.barang = {}  # kode -> {"nama", "stok", "versi"}
        self._muat()

    # ---------- persistensi (dipakai juga untuk recovery) ----------
    def _muat(self):
        if os.path.exists(self._path):
            with open(self._path, encoding="utf-8") as f:
                d = json.load(f)
            self.versi_global = d["versi_global"]
            self.barang = d["barang"]

    def _tulis(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump({"versi_global": self.versi_global, "barang": self.barang},
                      f, indent=2)

    def _simpan(self):
        self._tulis()
        if self.on_change:   # setiap perubahan data -> picu replikasi
            self.on_change(self.node_id, self.versi_global, copy.deepcopy(self.barang))

    def terapkan_snapshot(self, versi: int, barang: dict):
        """Dipakai recovery: ganti data lokal dengan snapshot dari replika."""
        with self._lock:
            self.versi_global = versi
            self.barang = barang
            self._tulis()

    def _naik_versi(self, kode):
        self.versi_global += 1
        self.barang[kode]["versi"] = self.versi_global

    # ---------- operasi ----------
    def tambah_barang(self, kode: str, nama: str, stok: int) -> dict:
        with self._lock:
            if kode in self.barang:
                raise StokError(f"barang {kode} sudah ada")
            if stok < 0:
                raise StokError("stok awal tidak boleh negatif")
            self.barang[kode] = {"nama": nama, "stok": stok, "versi": 0}
            self._naik_versi(kode)
            self._simpan()
            return {"kode": kode, **self.barang[kode]}

    def ubah_stok(self, kode: str, jumlah: int) -> dict:
        """jumlah = selisih (+ tambah, - kurang)."""
        with self._lock:
            b = self._ambil(kode)
            if b["stok"] + jumlah < 0:
                raise StokError(f"stok {kode} tidak cukup (sisa {b['stok']})")
            b["stok"] += jumlah
            self._naik_versi(kode)
            self._simpan()
            return {"kode": kode, **b}

    def hapus_barang(self, kode: str) -> dict:
        with self._lock:
            self._ambil(kode)
            del self.barang[kode]
            self.versi_global += 1
            self._simpan()
            return {"kode": kode, "dihapus": True}

    def get_stok(self, kode: str) -> dict:
        with self._lock:
            return {"kode": kode, **self._ambil(kode)}

    def hitung_total(self) -> dict:
        with self._lock:
            return {"jumlah_jenis": len(self.barang),
                    "total_stok": sum(b["stok"] for b in self.barang.values())}

    def daftar(self) -> dict:
        with self._lock:
            return {"versi_global": self.versi_global, "barang": dict(self.barang)}

    def _ambil(self, kode):
        if kode not in self.barang:
            raise StokError(f"barang {kode} tidak ditemukan")
        return self.barang[kode]
