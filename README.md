# Sistem Stok Barang Antar Cabang (Sistem Terdistribusi)

Proyek tugas mata kuliah Sistem Terdistribusi. Sistem ini adalah pengelolaan stok barang antar cabang yang berjalan di atas 4 node terpisah, dan di dalamnya diterapkan konsep RPC, RMI, REST API, sinkronisasi, dan fault tolerance dalam satu aplikasi yang utuh (bukan tiga proyek terpisah).

Tenggat tugas: 15 Oktober 2026 pukul 13.00.

## Daftar isi

1. Tentang proyek
2. Gambaran arsitektur
3. Implementasi dari RPC sampai fault tolerance
4. Techstack
5. Struktur direktori
6. Penjelasan direktori
7. Penjelasan file
8. Dokumentasi API
9. Cara menjalankan
10. Cara mengetes studi kasus
11. Membaca log
12. Batasan dan catatan desain
13. Ringkasan untuk laporan

---

## 1. Tentang proyek

### Studi kasus

Studi kasusnya adalah sistem inventaris stok barang antar cabang. Bayangkan sebuah usaha dengan kantor pusat dan dua cabang. Tiap cabang punya stok barangnya sendiri, dan barang bisa dipindahkan dari satu cabang ke cabang lain. Ada satu node tambahan yang menyimpan salinan data sebagai cadangan.

Operasi yang tersedia:

- tambah barang
- ubah stok (menambah atau mengurangi)
- hapus barang
- baca stok satu barang atau seluruh daftar
- hitung total stok
- transfer stok dari satu cabang ke cabang lain

Studi kasus ini dipilih karena semua materi tugas punya tempat yang wajar di dalamnya. Transfer stok antar cabang memerlukan pemanggilan antar node, perlu mencegah dua cabang mengubah barang yang sama pada saat bersamaan, datanya perlu disalin ke node cadangan, dan harus tetap berjalan ketika salah satu node mati.

### Peran keempat node

| Node | Nama | Peran |
|---|---|---|
| Node 1 | Pusat | Penyimpan data pusat dan pengelola lock utama (LockManager) |
| Node 2 | Cabang A | Menyimpan stok cabang A dan menjalankan transfer stok |
| Node 3 | Cabang B | Menyimpan stok cabang B dan menjalankan transfer stok |
| Node 4 | Replika | Menyimpan salinan data semua node, menjadi pengganti saat ada yang mati, dan menjadi lock manager cadangan |

Sesuai ketentuan tugas, satu anggota kelompok bertanggung jawab atas satu node. Untuk saat ini seluruh node dijalankan di satu komputer yang sama dengan alamat yang sama (127.0.0.1) dan port yang berbeda. Kodenya sudah disiapkan agar bisa dipindah ke komputer berbeda hanya dengan mengubah file `.env`.

---

## 2. Gambaran arsitektur

### Tiga lapisan dalam satu node

Setiap node menjalankan satu proses Python yang berisi tiga lapisan. Semua lapisan memakai logika yang sama sehingga tidak ada duplikasi aturan bisnis.

1. Lapisan REST API (Flask). Ini pintu masuk dari luar, misalnya dari Postman, curl, atau browser. Lapisan ini tidak memiliki logika bisnis, tugasnya hanya meneruskan permintaan ke RPC atau RMI lalu menerjemahkan hasilnya menjadi respons HTTP.
2. Lapisan RPC dan RMI. Ini pintu antar node. RPC (xmlrpc) dipakai untuk operasi data biasa, RMI (Pyro5) dipakai untuk objek remote yang punya state, seperti pengelola lock, cabang, dan replika.
3. Lapisan inti (core). Ini satu-satunya tempat logika stok berada, lengkap dengan penyimpanan ke file JSON.

### Topologi

Topologi yang dipilih adalah star, dengan Pusat sebagai pusat koordinasi. Permintaan lock selalu menuju Pusat. Untuk gambaran sederhananya:

```
                  Cabang A (Node 2)
                         |
Cabang B (Node 3) ---- Pusat (Node 1) ---- Replika (Node 4)
```

Ada satu catatan jujur yang sebaiknya disebutkan di laporan. Di luar jalur koordinasi lewat Pusat, ada dua jalur langsung yang dipakai demi efisiensi. Pertama, saat transfer stok, Cabang pengirim memanggil Cabang penerima langsung lewat RPC. Kedua, setiap node yang datanya berubah mengirim salinan langsung ke Replika. Jadi secara praktis topologinya star untuk koordinasi lock, dengan tambahan jalur langsung untuk transfer dan replikasi.

### Pembagian port

Setiap node punya tiga port, satu untuk tiap jenis layanan. Polanya mudah diingat: ribuan menunjukkan jenis layanan, satuan menunjukkan nomor node.

| Node | RPC (xmlrpc) | RMI (Pyro5) | REST API (Flask) |
|---|---|---|---|
| Node 1 (Pusat) | 5001 | 6001 | 8001 |
| Node 2 (Cabang A) | 5002 | 6002 | 8002 |
| Node 3 (Cabang B) | 5003 | 6003 | 8003 |
| Node 4 (Replika) | 5004 | 6004 | 8004 |

### Contoh alur: transfer stok

Misalnya pengguna memindahkan 20 unit BRG001 dari Cabang A ke Cabang B lewat Postman.

1. Postman mengirim `POST /transfer` ke API salah satu node (REST).
2. API meneruskannya ke objek `Cabang` di Node 2 lewat RMI.
3. Objek `Cabang` meminta lock untuk BRG001 ke `LockManager` di Pusat lewat RMI. Jika lock sedang dipegang node lain, ia menunggu dan mencoba lagi. Jika Pusat tidak tersedia, ia beralih ke lock manager cadangan di Node 4.
4. Setelah lock didapat, stok di Cabang A dikurangi, lalu Cabang A memanggil `ubah_stok` di Cabang B lewat RPC. Jika Cabang B gagal, stok di Cabang A dikembalikan (rollback).
5. Lock dilepas lewat RMI.
6. Karena data di Cabang A dan B berubah, keduanya mengirim salinan terbaru ke Node 4 (replikasi).
7. API membalas ke Postman dengan JSON berisi hasil dan statusnya.

Dalam satu permintaan, REST, RMI, dan RPC dipakai bersama dalam satu alur bisnis.

---

## 3. Implementasi dari RPC sampai fault tolerance

### 3.1 RPC

Implementasinya memakai modul `xmlrpc` bawaan Python. Pada RPC, node memanggil fungsi di node lain berdasarkan namanya, seolah-olah fungsi lokal. Klien hanya mengirim nama fungsi dan parameter, lalu menerima nilai kembalian. Tidak ada referensi objek.

Fungsi RPC yang tersedia di setiap node:

- `tambah_barang(kode, nama, stok)`
- `ubah_stok(kode, jumlah)`, di mana jumlah adalah selisih dan boleh negatif
- `hapus_barang(kode)`
- `get_stok(kode)`
- `hitung_total()`
- `daftar()`
- `ping()`, dipakai untuk heartbeat
- `atur_delay(detik)`, dipakai untuk mensimulasikan node yang lambat saat demo

Kode server ada di `src/common/rpc_server.py` dan kode klien di `src/common/rpc_client.py`.

### 3.2 RMI

Implementasinya memakai Pyro5. Pada RMI, node memanggil method pada objek yang hidup di node lain. Klien memegang proxy atau stub yang mewakili objek tersebut, dan objek di sisi server menyimpan state-nya sendiri.

Objek remote yang ada:

- `LockManager` di Node 1 (dan cadangannya di Node 4). Menyimpan daftar lock yang sedang aktif. Method: `acquire`, `release`, `status`.
- `Cabang` di Node 2 dan 3. Menyimpan jumlah transfer yang sudah dilakukan dan menjalankan transfer stok. Method: `transfer_stok`, `info`.
- `Replika` di Node 4. Menyimpan salinan data dari tiap node beserta nomor versinya. Method: `terima_replikasi`, `ambil_data_tertinggal`, `salinan`, `status`, `sinkron_ulang`.

Kode objek ada di `src/common/rmi_objects.py` dan kode klien (proxy) di `src/common/rmi_client.py`.

### 3.3 Perbedaan RPC dan RMI di dalam kode

| Aspek | RPC | RMI |
|---|---|---|
| Yang dipanggil | Fungsi, berdasarkan nama | Method pada objek remote |
| State | Tidak ada, fungsi berdiri sendiri | Objek menyimpan state sendiri |
| Sisi klien | Hanya nama fungsi dan parameter | Memegang proxy (stub) ke objek |
| Contoh di proyek ini | `get_stok("BRG001")` | `LockManager.acquire("BRG001", 2)` |
| Teknologi | `xmlrpc` | Pyro5 |
| File | `rpc_server.py`, `rpc_client.py` | `rmi_objects.py`, `rmi_client.py` |

Komentar penjelasan perbedaan ini juga ditulis langsung di bagian atas ketiga file tersebut, sesuai anjuran tugas.

Aturan praktis yang dipakai: operasi data sederhana lewat RPC, sedangkan operasi yang butuh koordinasi atau state (lock, transfer, replikasi) lewat RMI.

### 3.4 REST API

Implementasinya memakai Flask di `src/common/api.py`. Setiap node menjalankan API sendiri, dan setiap endpoint meneruskan permintaan ke pemanggilan RPC atau RMI. Respons selalu memuat field `via` (RPC atau RMI) dan `node_tujuan` supaya terlihat ke mana permintaan diteruskan. Daftar lengkap endpoint ada di bagian 8.

### 3.5 Sinkronisasi

Ada tiga mekanisme yang bekerja bersama.

Pertama, mutual exclusion dengan lock terpusat. Sebelum memindahkan stok sebuah barang, cabang harus mendapat lock untuk barang itu dari `LockManager`. Jika dua cabang mengubah barang yang sama bersamaan, satu mendapat lock dan yang lain menunggu. Setiap lock punya masa berlaku (lease) 10 detik sehingga lock milik node yang mati tidak menggantung selamanya.

Kedua, replikasi data berbasis nomor versi. Setiap perubahan data di Node 1, 2, atau 3 langsung dikirim ke Node 4. Setiap data punya nomor versi yang naik tiap perubahan. Replika hanya menerapkan salinan yang versinya lebih tinggi dari yang dimilikinya, sehingga kiriman yang datang terlambat atau terbalik urutan diabaikan dan data tidak rusak.

Ketiga, recovery. Ada dua arah:

- Node 4 yang baru hidup menarik data terbaru dari Node 1, 2, 3 (pull), sehingga mengejar perubahan yang terjadi selagi ia mati.
- Node 1, 2, 3 yang baru hidup menanyakan Node 4 apakah ada versi data yang lebih baru dari miliknya. Jika ada, datanya diperbarui. Ini berguna misalnya ketika file data sebuah cabang hilang.

Kode replikasi ada di `src/common/replikasi.py`, dan objek `Replika` ada di `rmi_objects.py`.

### 3.6 Fault tolerance

| Mekanisme | Cara kerja dan nilainya |
|---|---|
| Timeout | Batas tunggu 3 detik untuk setiap pemanggilan ke node lain |
| Retry | Maksimal 3 percobaan, dengan jeda exponential backoff 1 detik lalu 2 detik |
| Deteksi kegagalan | Heartbeat berupa ping tiap 2 detik. Node dinyatakan mati setelah 3 ping gagal berturut-turut, dan dinyatakan hidup lagi begitu satu ping berhasil |
| Failover baca | Jika node tujuan mati atau timeout, permintaan baca (GET) dijawab dari salinan di Replika |
| Failover lock | Jika Pusat tidak tersedia, cabang beralih ke lock manager cadangan di Node 4 |
| Lock yatim | Lock punya lease 10 detik, jadi lock milik node yang mati kadaluarsa sendiri |
| Rollback | Jika transfer gagal di tengah jalan, stok di cabang pengirim dikembalikan |
| Penanganan error | Sistem tidak crash. API membalas dengan kode status dan pesan yang jelas (502, 503, 504) |

Aturan retry yang perlu dipahami:

- Hanya kegagalan komunikasi (timeout atau node tidak terhubung) yang di-retry. Error bisnis seperti stok tidak cukup tidak di-retry.
- Operasi yang mengubah data (tambah, ubah, hapus, transfer) tidak di-retry ketika terjadi timeout. Alasannya, saat timeout permintaan bisa saja sudah dijalankan oleh node tujuan dan hanya balasannya yang hilang, sehingga mengulang berisiko menggandakan perubahan. Ketika node tidak terhubung sama sekali, permintaan pasti belum sampai, jadi retry aman dilakukan.
- Operasi yang mengubah data tidak dialihkan ke Replika saat node utama mati, supaya data tidak bercabang. Pengguna mendapat respons 503.

Kode dasarnya ada di `src/common/resilience.py` (retry dan backoff) dan `src/common/heartbeat.py` (deteksi kegagalan). Semua nilai di atas bisa diubah lewat `.env`.

---

## 4. Techstack

| Kebutuhan | Teknologi |
|---|---|
| Bahasa | Python 3.10 atau lebih baru (dikembangkan dengan Python 3.12) |
| RPC | `xmlrpc` (modul bawaan Python) |
| RMI | Pyro5 |
| REST API | Flask |
| Konfigurasi | python-dotenv (file `.env`) dan argumen command line (argparse) |
| Klien HTTP untuk alat uji | requests |
| Penyimpanan data | File JSON per node |
| Antarmuka | CLI dengan log yang informatif, dan REST API untuk akses dari luar |

---

## 5. Struktur direktori

```
stok-terdistribusi/
  .env
  .gitignore
  README.md
  requirements.txt
  data/                      (dibuat otomatis saat dijalankan)
  docs/
    API.md
  src/
    __init__.py
    common/
      __init__.py
      api.py
      bootstrap.py
      config.py
      core.py
      heartbeat.py
      logger.py
      replikasi.py
      resilience.py
      rmi_client.py
      rmi_objects.py
      rpc_client.py
      rpc_server.py
    node1_pusat/
      __init__.py
      main.py
    node2_cabang_a/
      __init__.py
      main.py
    node3_cabang_b/
      __init__.py
      main.py
    node4_replika/
      __init__.py
      main.py
    uji_rpc.py
    uji_rmi.py
    uji_sinkron.py
    uji_fault.py
```

---

## 6. Penjelasan direktori

| Direktori | Fungsi |
|---|---|
| Root proyek | Berisi konfigurasi dan dokumentasi: `.env`, `.gitignore`, `README.md`, `requirements.txt`. Semua perintah dijalankan dari sini |
| `data/` | Tempat penyimpanan data tiap node dalam bentuk JSON. Dibuat otomatis, tidak perlu dibuat manual, dan tidak dimasukkan ke Git |
| `docs/` | Dokumentasi tambahan. Saat ini berisi `API.md`, referensi endpoint lengkap dengan contoh respons |
| `src/` | Seluruh kode program |
| `src/common/` | Kode yang dipakai bersama oleh keempat node: logika stok, RPC, RMI, API, sinkronisasi, dan fault tolerance. Hampir semua pekerjaan ada di sini |
| `src/node1_pusat/` | Titik masuk (entry point) untuk Node 1, Pusat |
| `src/node2_cabang_a/` | Titik masuk untuk Node 2, Cabang A |
| `src/node3_cabang_b/` | Titik masuk untuk Node 3, Cabang B |
| `src/node4_replika/` | Titik masuk untuk Node 4, Replika |

Keempat folder node sengaja dibuat sangat tipis. Perbedaan perilaku antar node ditentukan oleh peran node di `config.py`, bukan oleh kode yang berbeda-beda. Dengan begitu satu anggota kelompok bisa memegang satu node tanpa kodenya berbeda jauh.

---

## 7. Penjelasan file

### File di root proyek

| File | Fungsi |
|---|---|
| `.env` | Konfigurasi host, port, dan parameter fault tolerance. Semua isinya opsional |
| `.gitignore` | Daftar file yang tidak ikut ke Git, misalnya `data/` dan `__pycache__/` |
| `README.md` | Dokumentasi ini |
| `requirements.txt` | Daftar library Python yang dibutuhkan |
| `docs/API.md` | Referensi endpoint API dengan contoh respons, termasuk respons error dan timeout |

### File di src/common (pekerjaan utama)

| File | Fungsi |
|---|---|
| `core.py` | Lapisan inti. Berisi kelas `StokStore` yang mengelola data barang (tambah, ubah, hapus, baca, hitung total), menyimpannya ke JSON, dan mengelola nomor versi. Juga punya hook `on_change` yang memicu replikasi setiap data berubah, dan `terapkan_snapshot` untuk recovery |
| `rpc_server.py` | Menjalankan server RPC (xmlrpc) yang membuka fungsi-fungsi dari `core.py`. Mengubah error bisnis menjadi respons terstruktur supaya server tidak crash. Juga menyediakan `ping` dan `atur_delay` |
| `rpc_client.py` | Fungsi `panggil_rpc(...)` untuk memanggil RPC di node lain, lengkap dengan timeout, retry, dan log |
| `rmi_objects.py` | Objek remote Pyro5: `LockManager`, `Cabang`, dan `Replika`, serta fungsi `jalankan_rmi` yang mendaftarkan objek sesuai peran node |
| `rmi_client.py` | Fungsi `panggil_rmi(...)` untuk memanggil method objek remote lewat proxy, dengan timeout, retry, dan log |
| `api.py` | Aplikasi Flask. Semua endpoint REST yang meneruskan permintaan ke RPC atau RMI, termasuk logika failover baca |
| `replikasi.py` | Replikasi data ke Node 4 (`pasang_replikasi`) dan recovery saat node hidup kembali (`pulihkan_dari_replika`) |
| `resilience.py` | Mekanisme retry dengan exponential backoff, aturan operasi mana yang boleh di-retry, dan fungsi menjawab permintaan baca dari salinan Replika |
| `heartbeat.py` | Detektor kegagalan. Tiap node mengirim ping berkala ke node lain dan mencatat node mana yang mati atau hidup kembali |
| `config.py` | Membaca konfigurasi (alamat, port, timeout, retry) dari argumen command line, `.env`, atau nilai default, dalam urutan prioritas itu. Juga menyimpan daftar node dan perannya |
| `logger.py` | Format log CLI yang seragam: siapa memanggil siapa, method, parameter, hasil, dan status |
| `bootstrap.py` | Fungsi `run_node(nomor)` yang menyalakan sebuah node: memuat data, menjalankan recovery, memasang replikasi, lalu menyalakan RPC, RMI, API, dan heartbeat |

### File titik masuk node

Setiap `main.py` di folder node hanya berisi satu panggilan `run_node(nomor)`.

| File | Fungsi |
|---|---|
| `src/node1_pusat/main.py` | Menjalankan Node 1 (Pusat) |
| `src/node2_cabang_a/main.py` | Menjalankan Node 2 (Cabang A) |
| `src/node3_cabang_b/main.py` | Menjalankan Node 3 (Cabang B) |
| `src/node4_replika/main.py` | Menjalankan Node 4 (Replika) |

File `__init__.py` di setiap folder sengaja dikosongkan. Fungsinya hanya agar Python mengenali folder tersebut sebagai paket sehingga perintah `python -m src.xxx` bisa berjalan.

### Alat uji di src

| File | Fungsi |
|---|---|
| `uji_rpc.py` | Menguji pemanggilan RPC, berupa skenario demo atau panggilan tunggal |
| `uji_rmi.py` | Menguji RMI: transfer stok, melihat lock aktif, melihat state objek Cabang, serta skenario konflik dua cabang |
| `uji_sinkron.py` | Menguji replikasi dan memeriksa apakah data tiap node konsisten dengan salinan di Replika |
| `uji_fault.py` | Menguji fault tolerance: memperlambat node secara sengaja, membaca dengan timeout dan retry, dan melihat status heartbeat |

---

## 8. Dokumentasi API

Setiap node punya API sendiri di port `800N` (N adalah nomor node), misalnya Node 2 di `http://127.0.0.1:8002`. Semua permintaan dan respons memakai JSON.

Endpoint yang berbasis RPC menerima parameter query `?node=` (1 sampai 4) untuk memilih node tujuan. Jika tidak diisi, tujuannya adalah node yang menerima permintaan.

### 8.1 Operasi data (diteruskan ke RPC)

| Method | Path | Body JSON | Fungsi |
|---|---|---|---|
| GET | `/barang` | - | Menampilkan seluruh barang beserta versi datanya |
| GET | `/barang/<kode>` | - | Menampilkan stok satu barang |
| POST | `/barang` | `kode`, `nama`, `stok` | Menambah barang baru |
| PUT | `/barang/<kode>/stok` | `jumlah` | Mengubah stok. Jumlah adalah selisih, nilai negatif untuk mengurangi |
| DELETE | `/barang/<kode>` | - | Menghapus barang |
| GET | `/total` | - | Menghitung jumlah jenis barang dan total stok |

### 8.2 Koordinasi antar node (diteruskan ke RMI)

| Method | Path | Body JSON | Fungsi |
|---|---|---|---|
| POST | `/transfer` | `kode`, `jumlah`, `dari` (2 atau 3), `ke` (2 atau 3), `delay` (opsional) | Memindahkan stok antar cabang, dengan lock dan rollback. Parameter `delay` menahan lock beberapa detik untuk keperluan demo |
| GET | `/lock` | - | Melihat lock yang sedang aktif di Pusat |
| GET | `/cabang/<2 atau 3>/info` | - | Melihat state objek Cabang (jumlah transfer dan total stok) |
| GET | `/replika` | - | Melihat status salinan di Replika (versi tiap node) |
| GET | `/replika/<1 sampai 3>` | - | Melihat isi salinan data sebuah node di Replika |
| POST | `/replika/sinkron-ulang` | - | Menyuruh Replika menarik data terbaru dari Node 1, 2, 3 |

### 8.3 Kesehatan node dan simulasi kegagalan

| Method | Path | Body JSON | Fungsi |
|---|---|---|---|
| GET | `/status` | - | Status keempat node (hidup, mati, atau timeout) beserta hasil heartbeat |
| GET | `/ping/<node>` | - | Ping satu node |
| POST | `/admin/delay/<node>` | `detik` | Sengaja memperlambat layanan sebuah node untuk mensimulasikan timeout. Isi 0 untuk mengembalikan normal |

### 8.4 Format respons

Respons berhasil:

```json
{
  "ok": true,
  "via": "RPC",
  "node_tujuan": 2,
  "data": { "kode": "BRG001", "nama": "Beras 5kg", "stok": 100, "versi": 1 }
}
```

Respons gagal:

```json
{
  "ok": false,
  "via": "RPC",
  "node_tujuan": 2,
  "error": "barang XXX tidak ditemukan"
}
```

Respons bisa memuat field tambahan: `percobaan` (berapa kali dicoba), `jenis_error` (timeout atau tidak_terhubung), `rollback` (transfer dibatalkan dan dikembalikan), dan `failover` (permintaan dijawab oleh Replika).

### 8.5 Kode status HTTP

| Kode | Arti |
|---|---|
| 200 | Berhasil. Bisa juga berarti dijawab lewat failover, lihat field `failover` |
| 201 | Berhasil dibuat (tambah barang) |
| 400 | Input tidak valid, misalnya body kurang atau nomor node di luar 1 sampai 4 |
| 404 | Barang tidak ditemukan |
| 409 | Konflik: barang sudah ada, atau lock sedang dipegang node lain |
| 422 | Aturan bisnis tidak terpenuhi, misalnya stok tidak cukup |
| 502 | Transfer dibatalkan dan dikembalikan karena node tujuan gagal |
| 503 | Node tujuan tidak dapat dihubungi setelah semua percobaan retry |
| 504 | Timeout menunggu node tujuan |

### 8.6 Contoh pemakaian dengan curl

Menambah barang di Cabang A:

```
curl -X POST http://127.0.0.1:8002/barang -H "Content-Type: application/json" -d '{"kode":"BRG001","nama":"Beras 5kg","stok":100}'
```

Membaca stok:

```
curl http://127.0.0.1:8002/barang/BRG001
```

Mengurangi stok 30 unit:

```
curl -X PUT http://127.0.0.1:8002/barang/BRG001/stok -H "Content-Type: application/json" -d '{"jumlah":-30}'
```

Memindahkan 20 unit dari Cabang A ke Cabang B:

```
curl -X POST http://127.0.0.1:8001/transfer -H "Content-Type: application/json" -d '{"kode":"BRG001","jumlah":20,"dari":2,"ke":3}'
```

Membaca data Node 3 lewat API Node 2:

```
curl "http://127.0.0.1:8002/barang?node=3"
```

Melihat status semua node:

```
curl http://127.0.0.1:8001/status
```

Untuk pengguna Windows: di Command Prompt, tanda kutip tunggal pada JSON tidak bekerja. Gunakan tanda kutip ganda dengan escape (`\"`), atau lebih mudah pakai Postman.

Contoh respons lengkap, termasuk respons error, timeout, dan failover, ada di `docs/API.md`.

---

## 9. Cara menjalankan

### 9.1 Prasyarat

- Python 3.10 atau lebih baru
- pip

### 9.2 Instalasi

Dari folder root proyek, disarankan memakai virtual environment:

```
python -m venv venv
```

Aktifkan virtual environment:

- Windows: `venv\Scripts\activate`
- Linux atau macOS: `source venv/bin/activate`

Lalu pasang dependensi:

```
pip install -r requirements.txt
```

### 9.3 Konfigurasi

Konfigurasi bersifat opsional. Tanpa file `.env` sama sekali, sistem tetap berjalan dengan nilai default: host `127.0.0.1`, port RPC `5000 + nomor node`, port RMI `6000 + nomor node`, dan port API `8000 + nomor node`.

Prioritas konfigurasi dari yang tertinggi:

1. Argumen command line
2. File `.env`
3. Nilai default di kode

Isi `.env` yang tersedia:

| Variabel | Default | Keterangan |
|---|---|---|
| `HOST` | 127.0.0.1 | Alamat untuk semua node |
| `HOST_NODE2`, `HOST_NODE3`, `HOST_NODE4` | mengikuti `HOST` | Alamat khusus satu node, dipakai kalau node dipindah ke komputer lain |
| `RPC_PORT_NODEn`, `RMI_PORT_NODEn`, `API_PORT_NODEn` | lihat tabel port | Mengubah port satu node |
| `RPC_TIMEOUT` | 3 | Batas tunggu tiap pemanggilan, dalam detik |
| `MAX_RETRY` | 3 | Jumlah percobaan maksimal per pemanggilan |
| `BACKOFF_BASE` | 1 | Jeda awal retry dalam detik, dikali 2 tiap percobaan |
| `HEARTBEAT_INTERVAL` | 2 | Jarak antar ping, dalam detik |
| `HEARTBEAT_GAGAL` | 3 | Jumlah ping gagal berturut-turut sebelum node dinyatakan mati |

Argumen command line yang tersedia untuk tiap node:

| Argumen | Fungsi |
|---|---|
| `--host` | Alamat tempat node ini menerima koneksi |
| `--rpc-port` | Port RPC node ini |
| `--rmi-port` | Port RMI node ini |
| `--api-port` | Port API node ini |
| `--data-dir` | Folder penyimpanan data (default: `data`) |

Contoh: `python -m src.node2_cabang_a.main --api-port 9002`

Catatan penting: argumen command line hanya mengubah port yang dipakai node itu sendiri. Node lain mencari alamatnya dari `.env`. Jadi jika kamu mengubah port sebuah node, ubah juga nilainya di `.env` supaya node lain tetap bisa menemukannya.

### 9.4 Menjalankan keempat node

Buka empat terminal, semuanya di folder root proyek. Satu terminal untuk satu node:

```
python -m src.node4_replika.main
python -m src.node1_pusat.main
python -m src.node2_cabang_a.main
python -m src.node3_cabang_b.main
```

Urutannya bebas, tetapi disarankan menyalakan Node 4 lebih dulu agar node lain bisa langsung berkomunikasi dengannya. Selalu gunakan `python -m ...` dari root proyek, bukan menjalankan file `main.py` langsung, supaya import antar folder bekerja.

Setelah menyala, setiap node menampilkan log seperti berikut:

```
[Node 2] === Node 2 (Cabang A) dimulai | data: 0 barang, versi 0 ===
[Node 2] RPC siap di 127.0.0.1:5002
[Node 2] RMI siap di 127.0.0.1:6002 (objek: cabang)
[Node 2] REST API siap di http://127.0.0.1:8002
[Node 2] HEARTBEAT aktif: ping tiap 2s, mati setelah 3 gagal berturut-turut
```

Untuk menghentikan sebuah node, tekan Ctrl+C di terminalnya.

### 9.5 Tentang folder data

Folder `data/` dibuat otomatis, dan file JSON di dalamnya baru muncul setelah ada perubahan data pertama. Isinya:

- `data_node1.json` sampai `data_node4.json`: data barang tiap node
- `replika_node4.json`: salinan data dari semua node yang disimpan Replika

Lokasi folder ini relatif terhadap tempat perintah dijalankan, jadi selalu jalankan dari root proyek.

### 9.6 Mengulang dari data bersih

Hentikan semua node, hapus seluruh isi folder `data/` (termasuk `replika_node4.json`), lalu nyalakan lagi. File replika perlu ikut dihapus karena jika masih ada, node yang datanya kosong akan menarik data lama itu lewat mekanisme recovery.

---

## 10. Cara mengetes studi kasus

Pastikan keempat node sudah menyala, lalu buka terminal kelima di root proyek. Karena beberapa skenario memakai data awal yang sama (BRG001), disarankan mengulang dari data bersih (bagian 9.6) sebelum tiap skenario besar.

### 10.1 Tes RPC

```
python -m src.uji_rpc
```

Skenario ini menjalankan delapan langkah: tambah barang, tambah barang duplikat, mengurangi stok, mengurangi melebihi stok, membaca stok, menghitung total, membaca barang yang tidak ada, menghapus barang, dan ping ke semua node.

Hasil yang diharapkan: langkah yang memang dirancang gagal (duplikat, stok kurang, barang tidak ada) menampilkan status GAGAL dengan pesan yang jelas, sedangkan sisanya BERHASIL. Itu menunjukkan penanganan error berjalan dengan benar.

Panggilan tunggal:

```
python -m src.uji_rpc <dari> <ke> <method> [parameter]
python -m src.uji_rpc 2 1 get_stok BRG001
```

### 10.2 Tes RMI dan mutual exclusion

```
python -m src.uji_rmi
```

Skenario ini menyiapkan BRG001 di Cabang A (100) dan Cabang B (50), lalu menjalankan transfer normal, transfer melebihi stok, melihat state objek Cabang, dan skenario konflik. Pada skenario konflik, dua cabang memindahkan barang yang sama hampir bersamaan. Cabang yang datang belakangan akan terlihat menunggu lock dengan log "menunggu...", lalu berjalan setelah lock dilepas. Hasil akhirnya total stok tetap 150 dan tidak ada lock yang tersisa.

Perintah manual:

```
python -m src.uji_rmi transfer 2 3 BRG001 10
python -m src.uji_rmi transfer 2 3 BRG001 10 5
python -m src.uji_rmi lock
python -m src.uji_rmi info 2
```

Perintah transfer dengan angka terakhir (5) menahan lock selama 5 detik, berguna untuk memperlihatkan lock aktif lewat perintah `lock`.

### 10.3 Tes REST API

Gunakan curl atau Postman dengan contoh di bagian 8.6. Urutan yang disarankan: cek `/status`, tambah barang, baca barang, ubah stok, transfer, lalu cek `/lock` dan `/replika`.

### 10.4 Tes sinkronisasi dan replikasi

```
python -m src.uji_sinkron
```

Skenario ini mengubah data di cabang, lalu memeriksa apakah salinan di Replika sama dengan data aslinya. Hasil yang diharapkan adalah baris "KONSISTEN" untuk setiap node setelah tiap langkah. Di log node akan terlihat proses sinkronisasi: kapan dimulai, node mana yang terlibat, dan hasil akhirnya.

Perintah lain:

```
python -m src.uji_sinkron konsisten
python -m src.uji_sinkron pull
```

Skenario recovery, Replika mati lalu hidup lagi:

1. Matikan Node 4 dengan Ctrl+C.
2. Ubah data, misalnya `python -m src.uji_rpc 2 2 ubah_stok BRG001 -5`. Di log Node 2 muncul pesan bahwa replikasi gagal dan datanya tertunda.
3. Nyalakan kembali Node 4. Ia otomatis menarik data terbaru dari node lain.
4. Jalankan `python -m src.uji_sinkron konsisten` dan semuanya harus kembali KONSISTEN.

Skenario recovery, data sebuah cabang hilang:

1. Matikan Node 2 lalu hapus file `data/data_node2.json`.
2. Nyalakan kembali Node 2. Di lognya muncul pesan recovery bahwa datanya diperbarui dari Node 4.

### 10.5 Tes fault tolerance

Skenario timeout dan retry:

```
python -m src.uji_fault delay 3 5
python -m src.uji_fault baca 3 BRG001
python -m src.uji_fault delay 3 0
```

Perintah pertama membuat Node 3 sengaja lambat (5 detik, lebih lama dari batas timeout 3 detik). Perintah kedua membaca dari Node 3 dan di log terlihat TIMEOUT pada percobaan 1 dan 2 sebelum akhirnya menyerah pada percobaan ke-3. Perintah ketiga mengembalikan Node 3 normal.

Skenario node mati lalu pulih:

1. Matikan Node 3 dengan Ctrl+C.
2. Di log node lain muncul pesan heartbeat bahwa Node 3 dinyatakan MATI.
3. Baca data Node 3 lewat API: `curl "http://127.0.0.1:8001/barang/BRG001?node=3"`. Hasilnya status 200 dengan field `failover`, artinya dijawab dari Replika.
4. Coba mengubah data Node 3: `curl -X PUT "http://127.0.0.1:8001/barang/BRG001/stok?node=3" -H "Content-Type: application/json" -d '{"jumlah":1}'`. Hasilnya 503 karena operasi ubah data memang tidak dialihkan.
5. Coba transfer ke Node 3 dengan `python -m src.uji_rmi transfer 2 3 BRG001 5`. Setelah semua percobaan retry gagal, hasilnya transfer dibatalkan dan stok di cabang pengirim dikembalikan (lewat API, statusnya 502).
6. Nyalakan kembali Node 3. Log menampilkan pesan bahwa Node 3 HIDUP kembali.

Skenario Pusat mati: matikan Node 1, lalu jalankan `python -m src.uji_rmi transfer 2 3 BRG001 5`. Di log terlihat percobaan ke Node 1 gagal, kemudian pesan FAILOVER ke lock manager cadangan di Node 4, dan transfer tetap berhasil.

Skenario node mati saat memegang lock:

1. Jalankan `python -m src.uji_rmi transfer 2 3 BRG001 5 20` agar Node 2 memegang lock selama 20 detik.
2. Segera matikan Node 2 dengan Ctrl+C.
3. Jalankan `python -m src.uji_rmi lock`. Terlihat lock BRG001 masih tercatat dipegang Node 2, lengkap dengan sisa waktunya yang terus berkurang.
4. Nyalakan kembali Node 2, lalu jalankan `python -m src.uji_rmi transfer 3 2 BRG001 1`. Transfer ini akan menunggu sampai lease 10 detik milik Node 2 habis, lalu berhasil. Ini membuktikan lock milik node yang mati tidak membuat sistem macet.

Melihat status semua node kapan saja:

```
python -m src.uji_fault status
```

### 10.6 Hal yang wajar terjadi

- Saat keempat node baru dinyalakan berurutan, node yang menyala lebih dulu bisa sempat mencatat bahwa node lain MATI, lalu HIDUP kembali ketika node itu menyala. Ini normal.
- Saat sebuah node sengaja dilambatkan, heartbeat juga akan menandainya MATI karena ping-nya ikut timeout, lalu HIDUP kembali setelah delay dikembalikan ke 0.
- Pada skenario timeout, permintaan ubah data yang timeout tetap bisa dieksekusi oleh node yang lambat setelah delay selesai. Ini perilaku sistem terdistribusi yang nyata, dan itulah alasan operasi ubah data tidak di-retry saat timeout.

---

## 11. Membaca log

Format log dirancang supaya mudah dibaca saat demo.

Baris dari sisi pemanggil:

```
[14:57:35] [Node 2 -> Node 1] RPC ubah_stok('BRG001', -30) => {'ok': True, ...} [BERHASIL]
```

Artinya, pada pukul 14:57:35 Node 2 memanggil Node 1, jenisnya RPC, method `ubah_stok` dengan parameter BRG001 dan -30, hasilnya sukses.

Baris dari sisi penerima:

```
[14:57:35] [Node 1] RPC diterima: ubah_stok('BRG001', -30) => {'ok': True, ...}
```

Status yang mungkin muncul: BERHASIL, GAGAL, dan TIMEOUT. Pada kegagalan komunikasi, statusnya memuat nomor percobaan dan jeda retry, misalnya:

```
TIMEOUT - percobaan 1/3, retry 1s lagi
TIMEOUT - menyerah setelah 3 percobaan
```

Penanda lain yang akan terlihat di log:

| Penanda | Artinya |
|---|---|
| SINKRON mulai / selesai / gagal | Proses replikasi data ke Replika |
| SINKRON (pull) | Replika menarik data dari node lain |
| RECOVERY | Node yang baru hidup mengejar data yang tertinggal |
| HEARTBEAT | Deteksi node mati atau hidup kembali |
| FAILOVER | Permintaan dialihkan ke node pengganti |
| FAULT INJECTION | Delay buatan diaktifkan untuk demo |

Pelaku `API Node N` pada log menandakan permintaan berasal dari lapisan REST API milik node tersebut, dan `Klien` menandakan permintaan dari alat uji.

---

## 12. Batasan dan catatan desain

Bagian ini sengaja ditulis terbuka supaya bisa langsung dipakai sebagai bahan pembahasan di laporan.

1. Semua node berjalan di satu komputer. Ini cukup untuk memenuhi tugas karena tiap node adalah proses terpisah yang berkomunikasi lewat jaringan (loopback), tetapi belum menguji kondisi jaringan antar komputer yang sesungguhnya.
2. Topologi star bersifat logis. Koordinasi lock memang berpusat di Pusat, tetapi transfer stok memakai jalur langsung antar cabang dan replikasi memakai jalur langsung ke Replika.
3. Pusat adalah titik kegagalan tunggal untuk koordinasi lock. Mitigasinya adalah lock manager cadangan di Node 4. Konsekuensinya, jika Pusat sebenarnya hidup tetapi tidak terjangkau oleh sebuah cabang, bisa terjadi dua pemegang lock sekaligus (split-brain). Lock yang dipegang di Pusat juga hilang bila Pusat mati, dan hanya terlindungi oleh lease.
4. Transfer stok bukan transaksi atomik penuh. Jika proses terputus tepat di antara pengurangan stok di pengirim dan penambahan di penerima (misalnya node pengirim mati di titik itu), data bisa tidak konsisten. Solusi lengkapnya adalah two-phase commit atau jurnal transaksi, yang di luar cakupan tugas ini. Kegagalan yang terdeteksi saat penambahan di penerima sudah ditangani dengan rollback.
5. Failover hanya untuk operasi baca. Data yang dijawab dari Replika bisa sedikit tertinggal dari data asli karena replikasi berjalan asinkron. Responsnya selalu menyebutkan versi salinan yang dipakai.
6. Retry untuk operasi ubah data hanya dilakukan ketika node tidak terhubung, bukan saat timeout (alasannya di bagian 3.6). Sistem ini memilih menghindari penggandaan perubahan, dengan konsekuensi klien harus memeriksa sendiri hasil operasi ubah data yang timeout.
7. Penyimpanan memakai file JSON per node, sederhana dan cukup untuk skala tugas. Belum ada mekanisme untuk menangani penulisan file yang terputus di tengah proses.
8. API belum memakai autentikasi, dan server Flask yang dipakai adalah server pengembangan bawaan. Keduanya wajar untuk keperluan tugas, tetapi bukan untuk produksi.
9. Sinkronisasi waktu (Cristian atau Berkeley) tidak dipakai. Sinkronisasi yang dipilih adalah replikasi data dan mutual exclusion, yang sesuai dengan studi kasus ini.

---

## 13. Ringkasan untuk laporan

### Pemetaan terhadap ketentuan tugas

| Ketentuan tugas | Pemenuhan di proyek ini |
|---|---|
| Jumlah node 4 | Pusat, Cabang A, Cabang B, Replika |
| Topologi dijelaskan dan konsisten | Star dengan Pusat sebagai koordinator lock (bagian 2) |
| Techstack bebas | Python, xmlrpc, Pyro5, Flask (bagian 4) |
| Antarmuka informatif | Log CLI memuat node pemanggil dan tujuan, method, parameter, hasil, dan status (bagian 11) |
| Studi kasus dengan banyak operasi | Stok antar cabang: tambah, ubah, hapus, baca, total, transfer |
| Implementasi RPC | `xmlrpc`, fungsi dipanggil per nama (bagian 3.1) |
| Implementasi RMI | Pyro5, objek LockManager, Cabang, Replika dengan proxy di sisi klien (bagian 3.2) |
| Perbedaan RPC dan RMI terlihat di kode | Komentar di `rpc_server.py`, `rmi_client.py`, `rmi_objects.py` dan tabel di bagian 3.3 |
| API meneruskan ke RPC atau RMI | Semua endpoint Flask meneruskan permintaan, dengan field `via` pada respons (bagian 8) |
| Dokumentasi endpoint | Bagian 8 dan `docs/API.md`, termasuk contoh respons error dan timeout |
| Sinkronisasi dengan skenario | Mutual exclusion dengan lock dan replikasi berversi. Skenario dua cabang mengubah barang yang sama (bagian 10.2 dan 10.4) |
| Fault tolerance saat timeout | Timeout, retry, heartbeat, failover, rollback (bagian 3.6) |
| Dampak pada sinkronisasi | Lock yatim ditangani lease. Node yang kembali hidup mengejar data lewat recovery (bagian 3.5) |
| Demo: matikan satu node saat berjalan | Skenario di bagian 10.5 |

### Nilai parameter yang dipakai

| Parameter | Nilai |
|---|---|
| Timeout per pemanggilan | 3 detik |
| Jumlah percobaan (retry) | Maksimal 3 percobaan |
| Jeda antar percobaan | 1 detik, lalu 2 detik (exponential backoff) |
| Interval heartbeat | 2 detik |
| Batas node dinyatakan mati | 3 ping gagal berturut-turut |
| Masa berlaku lock (lease) | 10 detik |
| Waktu tunggu maksimal untuk mendapat lock | 12 detik |

### Pembagian tanggung jawab per node

Karena satu anggota memegang satu node, ringkasan di bawah bisa dipakai untuk menjelaskan peran masing-masing.

| Node | Fokus penjelasan |
|---|---|
| Node 1 (Pusat) | Objek RMI `LockManager`, mutual exclusion, lease lock |
| Node 2 (Cabang A) dan Node 3 (Cabang B) | Objek RMI `Cabang`, transfer stok, penggabungan RPC dan RMI dalam satu alur, rollback |
| Node 4 (Replika) | Objek RMI `Replika`, replikasi berversi, recovery, failover baca, lock manager cadangan |

Fungsi yang sama (REST API, heartbeat, retry, logging) ada di keempat node karena berasal dari kode bersama di `src/common`.
