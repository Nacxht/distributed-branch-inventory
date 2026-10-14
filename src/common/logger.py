"""Log CLI yang informatif: siapa memanggil siapa, method, parameter, hasil, status."""
import threading
import time

_lock = threading.Lock()


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _cetak(teks: str) -> None:
    with _lock:
        print(teks, flush=True)


def _label(x) -> str:
    return f"Node {x}" if isinstance(x, int) else str(x)


def info(node_id: int, pesan: str) -> None:
    _cetak(f"[{_ts()}] [Node {node_id}] {pesan}")


def panggilan(pemanggil: int, tujuan: int, jenis: str, method: str,
              params, hasil, status: str) -> None:
    """status: BERHASIL | GAGAL | TIMEOUT. jenis: RPC | RMI | API."""
    _cetak(
        f"[{_ts()}] [{_label(pemanggil)} -> {_label(tujuan)}] {jenis} {method}"
        f"{params} => {hasil} [{status}]"
    )


def diterima(node_id: int, jenis: str, method: str, params, hasil) -> None:
    _cetak(f"[{_ts()}] [Node {node_id}] {jenis} diterima: {method}{params} => {hasil}")
