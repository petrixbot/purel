"""Auto-updates PeakMiner, probes Kryptex pools for the lowest-latency
region, then launches the miner against the fastest pool.
"""

import json
import os
import socket
import stat
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# --- wallet ------------------------------------------------------------
WALLET_ADDRESS = "prl1pesefvguavkq7f4z2zc65tftdfx3hfqm3dyf63h9zzypaupf8a5tsq2hl50"
WORKER_NAME = "PM5090-01"

# --- miner binary / release -------------------------------------------
BIN = "peakminer"
VER_FILE = ".peakminer.ver"
USER_AGENT = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
RELEASES_API = "https://api.github.com/repos/peakminer/peakminer/releases/latest"

# --- pool probing --------------------------------------------------------
POOL_PORT = 7048
PROBE_SAMPLES = 5
PROBE_TIMEOUT = 3.0
POOLS = {
    "global": "prl.kryptex.network",
    "europe": "prl-eu.kryptex.network",
    "north-america": "prl-us.kryptex.network",
    "south-america": "prl-br.kryptex.network",
    "singapore": "prl-sg.kryptex.network",
    "hongkong": "prl-hk.kryptex.network",
    "russia": "prl-ru.kryptex.network",
    "middle-east": "prl-ae.kryptex.network",
}


def log(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {level:<5} {msg}", flush=True)


# --- GitHub release lookup ----------------------------------------------

def http_get(url: str):
    req = urllib.request.Request(url, headers=USER_AGENT)
    return urllib.request.urlopen(req)


def fetch_latest_release() -> tuple[str, str]:
    """Return (tag, download_url) of the latest linux-x86_64 release."""
    release = json.loads(http_get(RELEASES_API).read().decode())
    tag = release["tag_name"]
    for asset in release["assets"]:
        name = asset["name"]
        if name.endswith("-linux-x86_64") and not name.endswith((".zip", ".tar.gz")):
            return tag, asset["browser_download_url"]
    raise RuntimeError("no linux-x86_64 asset in latest release")


# --- local version tracking ----------------------------------------------

def read_local_version() -> str:
    if os.path.isfile(VER_FILE):
        with open(VER_FILE) as f:
            return f.read().strip()
    return ""


def write_local_version(tag: str) -> None:
    with open(VER_FILE, "w") as f:
        f.write(tag)


# --- binary discovery / install ------------------------------------------

def install_binary(url: str) -> None:
    log("INFO", "downloading linux-x86_64 ...")
    with http_get(url) as resp, open(BIN, "wb") as f:
        f.write(resp.read())
    os.chmod(BIN, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    size_mib = os.path.getsize(BIN) / (1024 * 1024)
    log("INFO", f"download ok size={size_mib:.1f}MiB")


def ensure_binary_installed() -> str:
    """Install/update peakminer if needed and return its local path."""
    need_install = not os.path.isfile(BIN)
    local_tag = read_local_version() or "-"

    try:
        latest_tag, download_url = fetch_latest_release()
        if local_tag != latest_tag:
            need_install = True
        action = "download" if need_install else "skip"
        log("INFO", f"latest tag={latest_tag} local={local_tag} action={action}")
    except Exception as e:
        if not os.path.isfile(BIN):
            log("ERROR", f"latest lookup failed: {e}")
            raise
        log("WARN", f"latest lookup failed ({e}); using local binary")
        latest_tag = download_url = None

    if need_install and download_url:
        install_binary(download_url)
        write_local_version(latest_tag)

    if not os.path.isfile(BIN):
        raise RuntimeError(f"{BIN} not found")
    return BIN


# --- pool latency probing ------------------------------------------------

def probe_latency(host: str) -> float | None:
    """Return the best of PROBE_SAMPLES TCP connect times in ms, or None if
    every attempt failed."""
    best = None
    for _ in range(PROBE_SAMPLES):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(PROBE_TIMEOUT)
        t0 = time.perf_counter()
        try:
            sock.connect((host, POOL_PORT))
            ms = (time.perf_counter() - t0) * 1000
            if best is None or ms < best:
                best = ms
        except OSError:
            pass
        finally:
            sock.close()
    return best


def select_best_pool() -> str:
    """Probe every configured pool region and return the fastest as a
    stratum+tcp:// URL, falling back to the global pool if every probe
    fails."""
    log("INFO", f"probing {len(POOLS)} pools port={POOL_PORT} proto=tcp")

    results: dict[str, tuple[str, float | None]] = {}
    with ThreadPoolExecutor(max_workers=len(POOLS)) as executor:
        futures = {executor.submit(probe_latency, host): (region, host) for region, host in POOLS.items()}
        for future in as_completed(futures):
            region, host = futures[future]
            ms = future.result()
            results[region] = (host, ms)
            if ms is None:
                log("WARN", f"pool region={region:<14} rtt=timeout")
            else:
                log("INFO", f"pool region={region:<14} rtt={ms:6.1f}ms")

    reachable = [(region, host, ms) for region, (host, ms) in results.items() if ms is not None]
    if not reachable:
        host = POOLS["global"]
        url = f"stratum+tcp://{host}:{POOL_PORT}"
        log("WARN", f"all probes failed; fallback region=global url={url}")
        return url

    region, host, ms = min(reachable, key=lambda r: r[2])
    url = f"stratum+tcp://{host}:{POOL_PORT}"
    log("INFO", f"selected region={region} rtt={ms:.1f}ms url={url}")
    return url


# --- miner process ---------------------------------------------------------

def launch_miner(binary_path: str, pool_url: str) -> subprocess.Popen:
    cwd = os.path.dirname(os.path.abspath(binary_path)) or "."
    proc = subprocess.Popen(
        [
            f"./{BIN}",
            "--coin", "pearl",
            "-o", pool_url,
            "-u", f"{WALLET_ADDRESS}/{WORKER_NAME}",
        ],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    log("INFO", f"started pid={proc.pid} | worker={WORKER_NAME} | cwd={cwd}")
    return proc


def stream_output(proc: subprocess.Popen) -> int:
    print()
    for line in proc.stdout:
        print(line, end="")
        sys.stdout.flush()
    return proc.wait()


def main() -> None:
    binary_path = ensure_binary_installed()
    pool_url = select_best_pool()
    proc = launch_miner(binary_path, pool_url)
    code = stream_output(proc)
    log("ERROR" if code else "INFO", f"exited code={code}")


if __name__ == "__main__":
    main()
