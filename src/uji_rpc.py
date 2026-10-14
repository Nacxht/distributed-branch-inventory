"""Alat uji RPC dari command line.

Tanpa argumen  -> jalankan skenario demo (butuh node 1-4 sudah hidup).
Dengan argumen -> satu panggilan:
    python -m src.uji_rpc <dari> <ke> <method> [param...]
Contoh:
    python -m src.uji_rpc 2 1 get_stok BRG001
    python -m src.uji_rpc 3 1 ubah_stok BRG001 -10
"""
import sys

from src.common.rpc_client import panggil_rpc


def _auto(x):
    try:
        return int(x)
    except ValueError:
        return x


def demo():
    print("== 1. Cabang A menambah barang ke Pusat ==")
    panggil_rpc(2, 1, "tambah_barang", "BRG001", "Beras 5kg", 100)
    panggil_rpc(2, 1, "tambah_barang", "BRG002", "Minyak 2L", 50)
    print("\n== 2. Tambah duplikat (harus GAGAL) ==")
    panggil_rpc(2, 1, "tambah_barang", "BRG001", "Beras 5kg", 100)
    print("\n== 3. Cabang B mengurangi stok ==")
    panggil_rpc(3, 1, "ubah_stok", "BRG001", -30)
    print("\n== 4. Kurangi melebihi stok (harus GAGAL) ==")
    panggil_rpc(3, 1, "ubah_stok", "BRG001", -500)
    print("\n== 5. Baca stok & hitung total ==")
    panggil_rpc(2, 1, "get_stok", "BRG001")
    panggil_rpc(2, 1, "hitung_total")
    print("\n== 6. Barang tidak ada (harus GAGAL) ==")
    panggil_rpc(2, 1, "get_stok", "XXX")
    print("\n== 7. Hapus barang ==")
    panggil_rpc(2, 1, "hapus_barang", "BRG002")
    print("\n== 8. Ping semua node ==")
    for n in (1, 2, 3, 4):
        panggil_rpc(1, n, "ping")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        demo()
    elif len(sys.argv) >= 4:
        panggil_rpc(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3],
                    *[_auto(a) for a in sys.argv[4:]])
    else:
        print(__doc__)
