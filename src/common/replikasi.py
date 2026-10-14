"""SINKRONISASI DATA (replikasi) antar node.

Metode: replikasi primer -> replika (Node 4) dengan NOMOR VERSI.
  - PUSH : setiap perubahan data di Node 1/2/3 dikirim ke Node 4 (RMI Replika).
  - PULL : Node 4 yang baru hidup menarik data terbaru dari Node 1/2/3
           (Replika.sinkron_ulang), agar tidak tertinggal.
  - RECOVERY: node sumber yang hidup kembali menanyakan Node 4 apakah ada
           versi yang lebih baru dari miliknya (ambil_data_tertinggal).
Konflik penulisan bersamaan dicegah oleh LockManager (mutual exclusion);
urutan kiriman yang terbalik diatasi oleh pengecekan versi di Replika.
"""
import threading

from . import logger
from .rmi_client import panggil_rmi

REPLIKA = 4


def pasang_replikasi(node_id: int, store) -> None:
    def _push(sumber, versi, barang):
        logger.info(node_id, f"SINKRON mulai: replikasi data v{versi} "
                             f"({len(barang)} barang) -> Node {REPLIKA}")
        r = panggil_rmi(node_id, REPLIKA, "replika", "terima_replikasi",
                        sumber, versi, barang)
        if r.get("ok"):
            logger.info(node_id, f"SINKRON selesai: Node {REPLIKA} -> {r['data']['hasil']} "
                                 f"(versi replika v{r['data']['versi_replika']})")
        else:
            logger.info(node_id, f"SINKRON gagal: {r.get('error')}. Data v{versi} tertunda; "
                                 f"akan terkejar saat Node {REPLIKA} menarik data (pull) "
                                 f"atau pada perubahan berikutnya")

    def _on_change(sumber, versi, barang):
        threading.Thread(target=_push, args=(sumber, versi, barang), daemon=True).start()

    store.on_change = _on_change


def pulihkan_dari_replika(node_id: int, store) -> None:
    logger.info(node_id, f"RECOVERY: memeriksa Node {REPLIKA} (data lokal v{store.versi_global})")
    r = panggil_rmi(node_id, REPLIKA, "replika", "ambil_data_tertinggal",
                    node_id, store.versi_global, retry=False)
    if not r.get("ok"):
        logger.info(node_id, f"RECOVERY dilewati: {r.get('error')}; memakai data lokal")
        return
    d = r["data"]
    if d["lebih_baru"]:
        store.terapkan_snapshot(d["versi"], d["barang"])
        logger.info(node_id, f"RECOVERY selesai: data lokal tertinggal, diperbarui ke "
                             f"v{d['versi']} ({len(d['barang'])} barang) dari Node {REPLIKA}")
    else:
        logger.info(node_id, "RECOVERY selesai: data lokal sudah terbaru")
