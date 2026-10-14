"""Konfigurasi node. Prioritas: flag CLI > .env > default di kode."""
import argparse
import os

from dotenv import load_dotenv

load_dotenv()

NODES = {
    1: {"nama": "Pusat",    "peran": "pusat"},
    2: {"nama": "Cabang A", "peran": "cabang"},
    3: {"nama": "Cabang B", "peran": "cabang"},
    4: {"nama": "Replika",  "peran": "replika"},
}

_BASE_PORT = {"RPC": 5000, "RMI": 6000, "API": 8000}


def nama_node(node_id: int) -> str:
    return f"Node {node_id} ({NODES[node_id]['nama']})"


def host_of(node_id: int) -> str:
    return os.getenv(f"HOST_NODE{node_id}", os.getenv("HOST", "127.0.0.1"))


def port_of(jenis: str, node_id: int) -> int:
    """jenis: 'RPC' | 'RMI' | 'API'"""
    default = _BASE_PORT[jenis] + node_id
    return int(os.getenv(f"{jenis}_PORT_NODE{node_id}", default))


def rpc_url(node_id: int) -> str:
    return f"http://{host_of(node_id)}:{port_of('RPC', node_id)}"


def rmi_uri(node_id: int, nama_objek: str) -> str:
    return f"PYRO:{nama_objek}@{host_of(node_id)}:{port_of('RMI', node_id)}"


def api_url(node_id: int) -> str:
    return f"http://{host_of(node_id)}:{port_of('API', node_id)}"


def rpc_timeout() -> float:
    return float(os.getenv("RPC_TIMEOUT", "3"))


def max_retry() -> int:
    return int(os.getenv("MAX_RETRY", "3"))


def backoff_base() -> float:
    return float(os.getenv("BACKOFF_BASE", "1"))


def heartbeat_interval() -> float:
    return float(os.getenv("HEARTBEAT_INTERVAL", "2"))


def heartbeat_gagal() -> int:
    return int(os.getenv("HEARTBEAT_GAGAL", "3"))


def parse_args(node_id: int) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=f"Jalankan {nama_node(node_id)}")
    p.add_argument("--host", default=host_of(node_id), help="alamat bind node ini")
    p.add_argument("--rpc-port", type=int, default=port_of("RPC", node_id))
    p.add_argument("--rmi-port", type=int, default=port_of("RMI", node_id))
    p.add_argument("--api-port", type=int, default=port_of("API", node_id))
    p.add_argument("--data-dir", default="data", help="folder file JSON data")
    return p.parse_args()
