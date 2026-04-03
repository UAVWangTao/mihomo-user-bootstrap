#!/usr/bin/env python3
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_URLS = {
    "geoip.metadb": "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb",
    "geoip.dat": "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.dat",
    "geosite.dat": "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat",
}


def log(message: str) -> None:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def getenv(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or default


def download_to_staging(url: str, staging_path: Path, timeout: int) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "mihomo-geodata-updater/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()

    if not data:
        raise RuntimeError(f"downloaded empty file from {url}")

    staging_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=str(staging_path.parent), delete=False) as handle:
        handle.write(data)
        temp_path = Path(handle.name)

    temp_path.replace(staging_path)
    return staging_path


def maybe_reload_geo(controller_url: str, secret: str, timeout: int) -> None:
    if not controller_url or not secret:
        log("controller geo reload skipped because controller URL or secret is empty")
        return

    request = urllib.request.Request(
        f"{controller_url.rstrip('/')}/configs/geo",
        data=b'{"path":"","payload":""}',
        method="POST",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status >= 300:
            raise RuntimeError(f"controller geo reload failed with HTTP {response.status}")


def maybe_restart_service(service_name: str) -> None:
    if not service_name:
        return

    command = ["systemctl", "restart", service_name]
    log(f"restarting service as fallback: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise RuntimeError(f"failed to restart {service_name}:\n{detail}")


def main() -> int:
    geodata_dir = Path(getenv("GEODATA_DIR", "/etc/mihomo") or "/etc/mihomo")
    timeout = int(getenv("GEODATA_TIMEOUT", "600") or "600")
    controller_url = getenv("CONTROLLER_URL", "http://127.0.0.1:9090")
    controller_secret = getenv("CONTROLLER_SECRET", "")
    service_name = getenv("SERVICE_NAME", "mihomo.service") or "mihomo.service"
    restart_on_reload_fail = (getenv("RESTART_ON_RELOAD_FAIL", "1") or "1") == "1"

    targets = [
        ("geoip.metadb", getenv("GEOIP_URL", DEFAULT_URLS["geoip.metadb"]) or DEFAULT_URLS["geoip.metadb"]),
        ("geoip.dat", getenv("GEOIP_DAT_URL", DEFAULT_URLS["geoip.dat"]) or DEFAULT_URLS["geoip.dat"]),
        ("geosite.dat", getenv("GEOSITE_URL", DEFAULT_URLS["geosite.dat"]) or DEFAULT_URLS["geosite.dat"]),
    ]

    staged_files: list[tuple[Path, Path]] = []
    with tempfile.TemporaryDirectory(prefix="mihomo-geodata-", dir=str(geodata_dir)) as staging_dir:
        staging_root = Path(staging_dir)
        max_workers = min(3, len(targets))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {}
            for filename, url in targets:
                destination = geodata_dir / filename
                staging_path = staging_root / filename
                if destination.exists() and destination.stat().st_size > 0:
                    log(f"keeping current {filename} in use while downloading update")
                else:
                    log(f"{filename} missing locally; downloading initial copy")
                future = executor.submit(download_to_staging, url, staging_path, timeout)
                future_map[future] = (filename, destination, staging_path)

            for future in as_completed(future_map):
                filename, destination, staging_path = future_map[future]
                future.result()
                staged_files.append((destination, staging_path))
                log(f"staged new {filename} at {staging_path}")

        for destination, staging_path in staged_files:
            staging_path.replace(destination)
            log(f"activated new {destination.name}")

    try:
        maybe_reload_geo(controller_url, controller_secret, timeout)
        log("mihomo geodata reload completed through controller API")
    except Exception as exc:
        log(f"controller geo reload failed: {exc}")
        if restart_on_reload_fail:
            maybe_restart_service(service_name)
        else:
            raise

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        log(f"HTTP error while downloading geodata: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        log(f"network error while downloading geodata: {exc.reason}")
    except Exception as exc:
        log(f"geodata update failed: {exc}")
    raise SystemExit(1)
