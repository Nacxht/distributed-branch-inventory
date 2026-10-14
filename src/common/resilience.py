"""FAULT TOLERANCE: timeout, retry (exponential backoff), pembacaan dari salinan.

Parameter (bisa diubah di .env):
  RPC_TIMEOUT  = 3   detik batas tunggu per pemanggilan
  MAX_RETRY    = 3   jumlah percobaan maksimal per pemanggilan
  BACKOFF_BASE = 1   jeda antar percobaan: 1s, 2s, 4s, ... (x2 tiap percobaan)

Aturan retry:
  - Hanya kegagalan KOMUNIKASI yang di-retry (timeout / node tidak terhubung).
    Error bisnis (stok kurang, barang tidak ada) tidak pernah di-retry.
  - Operasi UBAH DATA (tambah/ubah/hapus/transfer) tidak di-retry saat TIMEOUT,
    karena permintaan mungkin sudah dieksekusi node tujuan (hanya balasannya yang
    hilang) sehingga retry berisiko menggandakan perubahan. Saat node TIDAK
    TERHUBUNG (permintaan pasti belum sampai) retry aman, jadi tetap dilakukan.
"""
import time

from . import config, logger

TIDAK_IDEMPOTEN = {"tambah_barang", "ubah_stok", "hapus_barang", "transfer_stok"}


def dengan_retry(pemanggil, tujuan, jenis, label, params, method, sekali,
                 retry=True, senyap=False):
    maks = config.max_retry() if retry else 1
    percobaan = 0
    while True:
        percobaan += 1
        hasil = sekali()
        je = hasil.get("jenis_error") if isinstance(hasil, dict) else None

        if je is None:  # komunikasi berhasil (hasil bisnis bisa ok / gagal)
            if not senyap:
                ok = (not isinstance(hasil, dict)) or hasil.get("ok", True)
                status = "BERHASIL" if ok else "GAGAL"
                if percobaan > 1:
                    status += f" pada percobaan ke-{percobaan}"
                logger.panggilan(pemanggil, tujuan, jenis, label, params, hasil, status)
            if percobaan > 1 and isinstance(hasil, dict):
                hasil["percobaan"] = percobaan
            return hasil

        nama = "TIMEOUT" if je == "timeout" else "GAGAL"
        boleh = (je == "tidak_terhubung") or (method not in TIDAK_IDEMPOTEN)
        if percobaan < maks and boleh:
            tunggu = config.backoff_base() * (2 ** (percobaan - 1))
            if not senyap:
                logger.panggilan(pemanggil, tujuan, jenis, label, params, hasil["error"],
                                 f"{nama} - percobaan {percobaan}/{maks}, retry {tunggu:g}s lagi")
            time.sleep(tunggu)
            continue

        if not senyap:
            alasan = "" if boleh else " (tidak di-retry: operasi ubah data, status tidak pasti)"
            logger.panggilan(pemanggil, tujuan, jenis, label, params, hasil["error"],
                             f"{nama} - menyerah setelah {percobaan} percobaan{alasan}")
        hasil["percobaan"] = percobaan
        return hasil


def dari_salinan(method, params, salinan):
    """Jawab permintaan BACA dari salinan Replika (failover). salinan={'versi','barang'}."""
    barang = salinan["barang"]
    if method == "daftar":
        return {"ok": True, "data": {"versi_global": salinan["versi"], "barang": barang}}
    if method == "get_stok":
        kode = params[0]
        if kode not in barang:
            return {"ok": False, "error": f"barang {kode} tidak ditemukan"}
        return {"ok": True, "data": {"kode": kode, **barang[kode]}}
    if method == "hitung_total":
        return {"ok": True, "data": {"jumlah_jenis": len(barang),
                                     "total_stok": sum(b["stok"] for b in barang.values())}}
    return {"ok": False, "error": f"{method} tidak dapat dijawab dari salinan"}
