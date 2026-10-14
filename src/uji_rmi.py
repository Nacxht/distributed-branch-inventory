"""Alat uji RMI (butuh node 1-4 hidup).

Tanpa argumen -> skenario demo: transfer stok, error, dan konflik lock.
Perintah manual:
    python -m src.uji_rmi transfer <dari> <ke> <kode> <jumlah> [delay]
    python -m src.uji_rmi lock          # lihat lock aktif di Pusat
    python -m src.uji_rmi info <node>   # state objek Cabang
"""
import sys
import threading
import time

from src.common.rmi_client import panggil_rmi
from src.common.rpc_client import panggil_rpc

KLIEN = "Klien"


def transfer(dari, ke, kode, jumlah, delay=0):
    return panggil_rmi(KLIEN, dari, "cabang", "transfer_stok", kode, jumlah, ke, delay,
                       timeout=30)


def demo():
    print("== 0. Siapkan data: BRG001 ada di Cabang A (100) dan Cabang B (50) ==")
    panggil_rpc(KLIEN, 2, "tambah_barang", "BRG001", "Beras 5kg", 100)
    panggil_rpc(KLIEN, 3, "tambah_barang", "BRG001", "Beras 5kg", 50)

    print("\n== 1. Transfer normal: Cabang A -> Cabang B, 20 unit ==")
    transfer(2, 3, "BRG001", 20)

    print("\n== 2. Transfer melebihi stok (harus GAGAL) ==")
    transfer(2, 3, "BRG001", 9999)

    print("\n== 3. Lihat state objek Cabang (RMI) ==")
    panggil_rmi(KLIEN, 2, "cabang", "info")

    print("\n== 4. KONFLIK: dua cabang memindahkan BRG001 BERSAMAAN ==")
    print("   A->B 10 unit (memproses 3 detik) vs B->A 5 unit (datang 0.5 detik kemudian)")
    t1 = threading.Thread(target=transfer, args=(2, 3, "BRG001", 10, 3))
    t2 = threading.Thread(target=transfer, args=(3, 2, "BRG001", 5, 0))
    t1.start(); time.sleep(0.5); t2.start()
    t1.join(); t2.join()

    print("\n== 5. Hasil akhir (total harus tetap 150) ==")
    a = panggil_rpc(KLIEN, 2, "get_stok", "BRG001")
    b = panggil_rpc(KLIEN, 3, "get_stok", "BRG001")
    if a.get("ok") and b.get("ok"):
        print(f"   Cabang A={a['data']['stok']}  Cabang B={b['data']['stok']}  "
              f"total={a['data']['stok'] + b['data']['stok']}")
    print("\n== 6. Lock aktif di Pusat (harus kosong) ==")
    panggil_rmi(KLIEN, 1, "lockmanager", "status")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        demo()
    elif a[0] == "transfer" and len(a) >= 5:
        transfer(int(a[1]), int(a[2]), a[3], int(a[4]), float(a[5]) if len(a) > 5 else 0)
    elif a[0] == "lock":
        panggil_rmi(KLIEN, 1, "lockmanager", "status")
    elif a[0] == "info" and len(a) == 2:
        panggil_rmi(KLIEN, int(a[1]), "cabang", "info")
    else:
        print(__doc__)
