"""LAPISAN 1 - REST API (Flask).

Tidak ada logika bisnis di sini. Setiap endpoint hanya MENERUSKAN permintaan
ke pemanggilan RPC (xmlrpc) atau RMI (Pyro5) di belakangnya, lalu menerjemahkan
hasilnya ke status HTTP + JSON. Respons selalu memuat "via" (RPC/RMI) dan
"node_tujuan" supaya terlihat ke mana permintaan diteruskan.
"""
import logging
import threading

from flask import Flask, jsonify, request

from . import config, logger
from . import heartbeat
from .resilience import dari_salinan
from .rmi_client import panggil_rmi
from .rpc_client import panggil_rpc

PUSAT = 1


def _status_http(r: dict, sukses: int) -> int:
    if r.get("ok"):
        return sukses
    je = r.get("jenis_error")
    if je == "timeout":
        return 504
    if je == "tidak_terhubung":
        return 503
    if r.get("rollback"):
        return 502
    if r.get("sebab") == "tidak_terhubung":
        return 503
    e = r.get("error", "")
    if "tidak ditemukan" in e:
        return 404
    if "sudah ada" in e or "dikunci" in e or "lock" in e:
        return 409
    if r.get("rollback"):
        return 502
    return 422


def buat_app(node_id: int) -> Flask:
    app = Flask(f"api_node{node_id}")
    app.json.ensure_ascii = False
    asal = f"API Node {node_id}"

    @app.after_request
    def _log(resp):
        logger.info(node_id, f"API {request.method} {request.full_path.rstrip('?')} => {resp.status_code}")
        return resp

    # ---------- helper ----------
    def body_dari(r, via, ke):
        body = {"ok": bool(r.get("ok")), "via": via, "node_tujuan": ke}
        if r.get("ok"):
            body["data"] = r.get("data")
        else:
            body["error"] = r.get("error")
            for k in ("jenis_error", "sebab"):
                if r.get(k):
                    body[k] = r[k]
            if r.get("rollback"):
                body["rollback"] = True
        if r.get("percobaan"):
            body["percobaan"] = r["percobaan"]
        return body

    def balas(r, via, ke, sukses=200):
        return jsonify(body_dari(r, via, ke)), _status_http(r, sukses)

    def galat(pesan, kode=400):
        return jsonify({"ok": False, "error": pesan}), kode

    def node_param(default):
        try:
            n = int(request.args.get("node", default))
        except ValueError:
            return None
        return n if n in config.NODES else None

    def body_json():
        return request.get_json(silent=True) or {}

    def rpc(method, *params, sukses=200):
        n = node_param(node_id)
        if n is None:
            return galat("parameter node harus 1-4")
        return balas(panggil_rpc(asal, n, method, *params), "RPC", n, sukses)

    def baca(method, *params):
        """BACA dengan FAILOVER: bila node tujuan mati/timeout, jawab dari salinan
        di Replika (Node 4). Operasi UBAH tidak dialihkan (lihat dokumentasi)."""
        n = node_param(node_id)
        if n is None:
            return galat("parameter node harus 1-4")
        r = panggil_rpc(asal, n, method, *params)
        if r.get("ok") or n == 4 or r.get("jenis_error") not in ("timeout", "tidak_terhubung"):
            return balas(r, "RPC", n)
        logger.info(node_id, f"FAILOVER: Node {n} {r['jenis_error']}, membaca salinan dari Node 4 (Replika)")
        rep = panggil_rmi(asal, 4, "replika", "salinan", n)
        if not rep.get("ok"):
            logger.info(node_id, "FAILOVER gagal: Replika tidak punya salinan / tidak tersedia")
            return balas(r, "RPC", n)
        hasil = dari_salinan(method, params, rep["data"])
        body = body_dari(hasil, "RPC -> RMI (failover ke Replika)", 4)
        body["failover"] = {"node_asal": n, "node_pengganti": 4,
                            "alasan": r["jenis_error"], "percobaan": r.get("percobaan"),
                            "versi_salinan": rep["data"]["versi"],
                            "catatan": "data dari salinan Replika, mungkin sedikit tertinggal"}
        return jsonify(body), _status_http(hasil, 200)

    # ---------- RPC-backed: operasi data ----------
    @app.get("/barang")
    def daftar():
        return baca("daftar")

    @app.get("/barang/<kode>")
    def get_barang(kode):
        return baca("get_stok", kode)

    @app.post("/barang")
    def tambah():
        b = body_json()
        if not all(k in b for k in ("kode", "nama", "stok")) or not isinstance(b["stok"], int):
            return galat("body wajib: kode (str), nama (str), stok (int)")
        return rpc("tambah_barang", b["kode"], b["nama"], b["stok"], sukses=201)

    @app.put("/barang/<kode>/stok")
    def ubah(kode):
        b = body_json()
        if not isinstance(b.get("jumlah"), int):
            return galat("body wajib: jumlah (int, boleh negatif)")
        return rpc("ubah_stok", kode, b["jumlah"])

    @app.delete("/barang/<kode>")
    def hapus(kode):
        return rpc("hapus_barang", kode)

    @app.get("/total")
    def total():
        return baca("hitung_total")

    # ---------- RMI-backed: objek remote ----------
    @app.post("/transfer")
    def transfer():
        b = body_json()
        try:
            kode, jumlah = b["kode"], int(b["jumlah"])
            dari, ke = int(b["dari"]), int(b["ke"])
            delay = float(b.get("delay", 0))
        except (KeyError, ValueError, TypeError):
            return galat("body wajib: kode, jumlah, dari (2/3), ke (2/3); opsional: delay")
        if dari not in (2, 3):
            return galat("dari harus 2 atau 3 (node cabang)")
        r = panggil_rmi(asal, dari, "cabang", "transfer_stok", kode, jumlah, ke, delay, timeout=30)
        return balas(r, "RMI", dari)

    @app.get("/lock")
    def lock():
        return balas(panggil_rmi(asal, PUSAT, "lockmanager", "status"), "RMI", PUSAT)

    @app.get("/cabang/<int:n>/info")
    def info_cabang(n):
        if n not in (2, 3):
            return galat("node cabang hanya 2 atau 3")
        return balas(panggil_rmi(asal, n, "cabang", "info"), "RMI", n)

    # ---------- RMI-backed: replika (sinkronisasi) ----------
    @app.get("/replika")
    def replika_status():
        return balas(panggil_rmi(asal, 4, "replika", "status"), "RMI", 4)

    @app.get("/replika/<int:sumber>")
    def replika_salinan(sumber):
        return balas(panggil_rmi(asal, 4, "replika", "salinan", sumber), "RMI", 4)

    @app.post("/replika/sinkron-ulang")
    def replika_tarik():
        return balas(panggil_rmi(asal, 4, "replika", "sinkron_ulang", timeout=30), "RMI", 4)

    # ---------- fault injection (untuk demo) ----------
    @app.post("/admin/delay/<int:n>")
    def admin_delay(n):
        b = body_json()
        try:
            detik = float(b["detik"])
        except (KeyError, ValueError, TypeError):
            return galat("body wajib: detik (angka, 0 = normal)")
        if n not in config.NODES:
            return galat("node harus 1-4")
        return balas(panggil_rpc(asal, n, "atur_delay", detik, retry=False), "RPC", n)

    # ---------- kesehatan node ----------
    @app.get("/ping/<int:n>")
    def ping(n):
        if n not in config.NODES:
            return galat("node harus 1-4")
        r = panggil_rpc(asal, n, "ping", retry=False)
        if r == "pong":
            return jsonify({"ok": True, "via": "RPC", "node_tujuan": n, "data": "pong"})
        return balas(r, "RPC", n)

    @app.get("/status")
    def status():
        hasil = {}
        det = heartbeat.detektor()
        hb = det.ringkas() if det else {}
        for n, info in config.NODES.items():
            r = panggil_rpc(asal, n, "ping", retry=False, senyap=True)
            if r == "pong":
                st = "hidup"
            else:
                st = "timeout" if r.get("jenis_error") == "timeout" else "mati"
            hasil[f"node{n}"] = {"nama": info["nama"], "status": st}
            if n in hb:
                hasil[f"node{n}"]["heartbeat"] = ("hidup" if hb[n]["hidup"] else "MATI")
                hasil[f"node{n}"]["ping_gagal_beruntun"] = hb[n]["gagal_beruntun"]
        return jsonify({"ok": True, "via": "RPC", "data": hasil})

    return app


def jalankan_api(node_id: int, host: str, port: int):
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = buat_app(node_id)
    t = threading.Thread(
        target=lambda: app.run(host=host, port=port, threaded=True, use_reloader=False),
        daemon=True)
    t.start()
    logger.info(node_id, f"REST API siap di http://{host}:{port}")
    return app
