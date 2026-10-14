"""Alat uji sinkronisasi/replikasi (butuh node 1-4 hidup).

Tanpa argumen -> demo: data berubah di cabang, lalu diperiksa konsistensinya
                 dengan salinan di Replika (Node 4).
    python -m src.uji_sinkron konsisten   # cek saja
    python -m src.uji_sinkron pull        # suruh Node 4 menarik data (catch-up)
"""
import sys
import threading
import time

from src.common.rmi_client import panggil_rmi
from src.common.rpc_client import panggil_rpc
from src.uji_rmi import transfer

KLIEN = "Klien"


def konsisten():
    time.sleep(0.7)   # replikasi berjalan asinkron
    for sumber in (1, 2, 3):
        src = panggil_rpc(KLIEN, sumber, "daftar")
        rep = panggil_rmi(KLIEN, 4, "replika", "salinan", sumber)
        if not src.get("ok"):
            print(f"   >> Node {sumber}: tidak dapat dibaca"); continue
        if not rep.get("ok"):
            if rep.get("jenis_error"):
                print(f"   >> Node {sumber}: Replika tidak dapat dihubungi ({rep['jenis_error']})")
            elif src["data"]["versi_global"] == 0:
                print(f"   >> Node {sumber}: belum ada perubahan data (tidak perlu replikasi)")
            else:
                print(f"   >> Node {sumber} v{src['data']['versi_global']}: Replika BELUM punya salinan (tertinggal)")
            continue
        s, r = src["data"], rep["data"]
        sama = s["versi_global"] == r["versi"] and s["barang"] == r["barang"]
        print(f"   >> Node {sumber} v{s['versi_global']} vs Replika v{r['versi']}: "
              f"{'KONSISTEN' if sama else 'BERBEDA'}")


def demo():
    print("== 1. Data berubah di Cabang A dan B -> direplikasi ke Node 4 ==")
    panggil_rpc(KLIEN, 2, "tambah_barang", "BRG001", "Beras 5kg", 100)
    panggil_rpc(KLIEN, 3, "tambah_barang", "BRG001", "Beras 5kg", 50)
    konsisten()
    print("\n== 2. Transfer A->B (mengubah dua node) ==")
    transfer(2, 3, "BRG001", 20)
    konsisten()
    print("\n== 3. Dua cabang mengubah barang yang sama bersamaan ==")
    t1 = threading.Thread(target=transfer, args=(2, 3, "BRG001", 10, 3))
    t2 = threading.Thread(target=transfer, args=(3, 2, "BRG001", 5, 0))
    t1.start(); time.sleep(0.5); t2.start(); t1.join(); t2.join()
    konsisten()
    print("\n== 4. Status Replika ==")
    panggil_rmi(KLIEN, 4, "replika", "status")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        demo()
    elif a[0] == "konsisten":
        konsisten()
    elif a[0] == "pull":
        panggil_rmi(KLIEN, 4, "replika", "sinkron_ulang", timeout=30)
    else:
        print(__doc__)
