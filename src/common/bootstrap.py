"""Menyalakan sebuah node. Setiap nodeX/main.py cukup memanggil run_node(X).

Tahap sekarang: RPC + RMI + REST API (masing-masing di thread sendiri).
"""
import threading

from . import config, logger
from .core import StokStore
from .api import jalankan_api
from .heartbeat import mulai_heartbeat
from .replikasi import pasang_replikasi, pulihkan_dari_replika
from .rmi_objects import jalankan_rmi
from .rpc_server import jalankan_rpc


def run_node(node_id: int):
    args = config.parse_args(node_id)
    store = StokStore(node_id, args.data_dir)

    logger.info(node_id, f"=== {config.nama_node(node_id)} dimulai | "
                         f"data: {len(store.barang)} barang, versi {store.versi_global} ===")
    peran = config.NODES[node_id]["peran"]
    if peran != "replika":
        pulihkan_dari_replika(node_id, store)   # recovery: kejar data tertinggal
        pasang_replikasi(node_id, store)        # tiap perubahan -> replikasi ke Node 4

    jalankan_rpc(node_id, store, args.host, args.rpc_port)
    _, objek = jalankan_rmi(node_id, store, args.host, args.rmi_port)
    jalankan_api(node_id, args.host, args.api_port)
    mulai_heartbeat(node_id)   # deteksi kegagalan node lain

    if peran == "replika":
        threading.Thread(target=objek.sinkron_ulang, daemon=True).start()  # catch-up saat start

    try:
        threading.Event().wait()   # tahan proses tetap hidup
    except KeyboardInterrupt:
        logger.info(node_id, "dihentikan")
