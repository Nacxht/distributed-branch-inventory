# Dokumentasi REST API

Setiap node menjalankan API sendiri: **Node N -> `http://127.0.0.1:800N`**
(Pusat 8001, Cabang A 8002, Cabang B 8003, Replika 8004).

API tidak berisi logika bisnis. Setiap endpoint **meneruskan** permintaan ke
pemanggilan **RPC** (xmlrpc) atau **RMI** (Pyro5) di belakangnya. Respons selalu
memuat `via` (RPC/RMI) dan `node_tujuan`.

Endpoint berbasis RPC menerima query `?node=1..4` untuk memilih node tujuan
(default: node yang menerima request).

## Daftar endpoint

| Method | Path | Body (JSON) | Diteruskan ke |
|---|---|---|---|
| GET | `/barang` | - | RPC `daftar` |
| GET | `/barang/<kode>` | - | RPC `get_stok` |
| POST | `/barang` | `kode`, `nama`, `stok` | RPC `tambah_barang` |
| PUT | `/barang/<kode>/stok` | `jumlah` (selisih, boleh negatif) | RPC `ubah_stok` |
| DELETE | `/barang/<kode>` | - | RPC `hapus_barang` |
| GET | `/total` | - | RPC `hitung_total` |
| POST | `/transfer` | `kode`, `jumlah`, `dari` (2/3), `ke` (2/3), opsional `delay` | RMI `Cabang.transfer_stok` (+ RMI lock, RPC ubah stok) |
| GET | `/lock` | - | RMI `LockManager.status` |
| GET | `/cabang/<2 atau 3>/info` | - | RMI `Cabang.info` |
| GET | `/replika` | - | RMI `Replika.status` |
| GET | `/replika/<node sumber 1-3>` | - | RMI `Replika.salinan` |
| POST | `/replika/sinkron-ulang` | - | RMI `Replika.sinkron_ulang` (Node 4 menarik data terbaru) |
| POST | `/admin/delay/<node>` | `detik` (0 = normal) | RPC `atur_delay` (fault injection untuk demo timeout) |
| GET | `/ping/<node>` | - | RPC `ping` |
| GET | `/status` | - | RPC `ping` ke semua node |

## Kode status HTTP

| Kode | Arti |
|---|---|
| 200 / 201 | berhasil / berhasil dibuat (200 juga bila dijawab lewat **failover** ke Replika, lihat field `failover`) |
| 400 | input tidak valid (body kurang, node di luar 1-4) |
| 404 | barang tidak ditemukan |
| 409 | konflik (barang sudah ada, atau lock sedang dipegang node lain) |
| 422 | aturan bisnis gagal (mis. stok tidak cukup) |
| 502 | transfer dibatalkan dan di-rollback karena node tujuan gagal |
| 503 | node tujuan tidak dapat dihubungi (mati) setelah semua percobaan retry |
| 504 | **timeout** menunggu node tujuan |

## Contoh (curl)

```bash
# tambah barang di Cabang A (lewat API Cabang A)
curl -X POST http://127.0.0.1:8002/barang -H "Content-Type: application/json" \
     -d '{"kode":"BRG001","nama":"Beras 5kg","stok":100}'

# baca stok
curl http://127.0.0.1:8002/barang/BRG001

# ubah stok (-30)
curl -X PUT http://127.0.0.1:8002/barang/BRG001/stok -H "Content-Type: application/json" \
     -d '{"jumlah":-30}'

# transfer Cabang A -> Cabang B (RMI + RPC)
curl -X POST http://127.0.0.1:8001/transfer -H "Content-Type: application/json" \
     -d '{"kode":"BRG001","jumlah":20,"dari":2,"ke":3}'

# akses node lain lewat parameter node
curl "http://127.0.0.1:8002/barang?node=3"

# status semua node
curl http://127.0.0.1:8001/status
```

(Di Windows CMD, gunakan tanda kutip ganda dan escape `\"` pada JSON, atau pakai Postman.)

## Contoh respons (hasil uji nyata)

**201 - tambah barang (RPC)**
```json
{"data":{"kode":"BRG001","nama":"Beras 5kg","stok":100,"versi":1},"node_tujuan":2,"ok":true,"via":"RPC"}
```

**409 - barang sudah ada**
```json
{"error":"barang BRG001 sudah ada","node_tujuan":2,"ok":false,"via":"RPC"}
```

**404 - barang tidak ditemukan**
```json
{"error":"barang XXX tidak ditemukan","node_tujuan":2,"ok":false,"via":"RPC"}
```

**422 - stok tidak cukup**
```json
{"error":"stok BRG001 tidak cukup (sisa 70)","node_tujuan":2,"ok":false,"via":"RPC"}
```

**400 - input tidak valid**
```json
{"error":"body wajib: kode (str), nama (str), stok (int)","ok":false}
```

**200 - transfer (RMI)**
```json
{"data":{"dari":2,"jumlah":20,"ke":3,"kode":"BRG001","stok_lokal":50},"node_tujuan":2,"ok":true,"via":"RMI"}
```

**200 - lock aktif di Pusat (RMI)**
```json
{"data":{},"node_tujuan":1,"ok":true,"via":"RMI"}
```

**504 - TIMEOUT (node tujuan tidak merespons dalam batas waktu)**
```json
{"error":"timeout ke Node 4","jenis_error":"timeout","node_tujuan":4,"ok":false,"via":"RPC"}
```

**503 - node mati (koneksi ditolak)**
```json
{"error":"Node 3 tidak dapat dihubungi","jenis_error":"tidak_terhubung","node_tujuan":3,"ok":false,"via":"RPC"}
```
(Respons 503 mengikuti format yang sama; muncul bila node tujuan dimatikan.)

**200 - status semua node**
```json
{"data":{"node1":{"nama":"Pusat","status":"hidup"},"node2":{"nama":"Cabang A","status":"hidup"},
         "node3":{"nama":"Cabang B","status":"hidup"},"node4":{"nama":"Replika","status":"timeout"}},
 "ok":true,"via":"RPC"}
```

## Fault tolerance pada API

- **Timeout** 3 dtk per pemanggilan, **retry** maksimal 3 percobaan dengan exponential backoff (1s, 2s).
  Field `percobaan` pada respons menunjukkan berapa kali dicoba.
- Operasi **baca** (GET) yang node tujuannya mati/timeout **dialihkan (failover)** ke salinan di Replika (Node 4).
  Operasi **ubah data** tidak dialihkan (agar data tidak bercabang) dan membalas 503/504.
- Operasi ubah data tidak di-retry saat **timeout** (permintaan mungkin sudah dieksekusi; retry bisa menggandakan perubahan),
  tetapi di-retry saat node **tidak terhubung** (permintaan pasti belum sampai).

**200 - baca dengan failover (Node 3 mati, dijawab dari Replika)**
```json
{"data":{"kode":"BRG001","nama":"Beras 5kg","stok":50,"versi":2},
 "failover":{"alasan":"tidak_terhubung","node_asal":3,"node_pengganti":4,"versi_salinan":2,"percobaan":3,
             "catatan":"data dari salinan Replika, mungkin sedikit tertinggal"},
 "node_tujuan":4,"ok":true,"via":"RPC -> RMI (failover ke Replika)"}
```

**503 - ubah data ke node mati (setelah 3 percobaan)**
```json
{"error":"Node 3 tidak dapat dihubungi","jenis_error":"tidak_terhubung","node_tujuan":3,"ok":false,"percobaan":3,"via":"RPC"}
```

**504 - ubah data ke node lambat (tidak di-retry)**
```json
{"error":"timeout ke Node 3","jenis_error":"timeout","node_tujuan":3,"ok":false,"percobaan":1,"via":"RPC"}
```

**502 - transfer dibatalkan (node tujuan mati), stok asal dikembalikan**
```json
{"error":"transfer dibatalkan: Node 3 tidak dapat dihubungi","node_tujuan":2,"ok":false,"rollback":true,"sebab":"tidak_terhubung","via":"RMI"}
```

**Fault injection untuk demo**
```bash
curl -X POST http://127.0.0.1:8001/admin/delay/3 -H "Content-Type: application/json" -d '{"detik":5}'   # lambatkan Node 3
curl -X POST http://127.0.0.1:8001/admin/delay/3 -H "Content-Type: application/json" -d '{"detik":0}'   # normal lagi
```
