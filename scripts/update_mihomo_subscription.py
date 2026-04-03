#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml


def log(message: str) -> None:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def getenv(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or default


def require_env(name: str) -> str:
    value = getenv(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def load_yaml_file(path: Path) -> dict:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise RuntimeError(f"YAML root must be a mapping: {path}")

    return data


def deep_merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        result = dict(base)
        for key, value in override.items():
            if key in result:
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    return override


def fetch_subscription(url: str, user_agent: str, timeout: int) -> tuple[str, dict]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/yaml,text/yaml,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", "replace")
        headers = dict(response.headers.items())
    return body, headers


def download_file(url: str, destination: Path, timeout: int) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "mihomo-subscription-updater/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=str(destination.parent), delete=False) as handle:
        handle.write(data)
        temp_path = Path(handle.name)

    temp_path.replace(destination)


def validate_yaml_mapping(raw_text: str) -> dict:
    try:
        data = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"subscription is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("subscription root is not a YAML mapping")

    if not isinstance(data.get("proxies"), list):
        raise RuntimeError("subscription YAML does not contain a proxies list")

    return data


def dump_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            data,
            handle,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )


def test_config(mihomo_bin: str, geodata_dir: Path, config_path: Path, timeout: int) -> None:
    command = [mihomo_bin, "-d", str(geodata_dir), "-t", "-f", str(config_path)]
    log(f"validating config: {' '.join(command)}")
    result = subprocess.run(command, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"mihomo config test failed with exit code {result.returncode}")


def reload_controller(controller_url: str, secret: str, config_path: Path, timeout: int) -> None:
    payload = json.dumps({"path": str(config_path)}).encode("utf-8")
    request = urllib.request.Request(
        f"{controller_url.rstrip('/')}/configs?force=true",
        data=payload,
        method="PUT",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status >= 300:
            raise RuntimeError(f"controller reload failed with HTTP {response.status}")


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
    subscription_url = require_env("SUBSCRIPTION_URL")
    user_agent = getenv("SUBSCRIPTION_USER_AGENT", "Clash.Meta") or "Clash.Meta"
    request_timeout = int(getenv("REQUEST_TIMEOUT", "30") or "30")
    geodata_timeout = int(getenv("GEODATA_TIMEOUT", "600") or "600")

    override_path = Path(getenv("OVERRIDE_CONFIG", "/etc/mihomo/override.yaml") or "/etc/mihomo/override.yaml")
    output_path = Path(getenv("OUTPUT_CONFIG", "/etc/mihomo/config.yaml") or "/etc/mihomo/config.yaml")
    cache_path = Path(
        getenv("SUBSCRIPTION_CACHE", "/etc/mihomo/subscription.yaml") or "/etc/mihomo/subscription.yaml"
    )
    backup_path = Path(
        getenv("BACKUP_CONFIG", f"{output_path}.bak") or f"{output_path}.bak"
    )
    mihomo_bin = getenv("MIHOMO_BIN", "/opt/mihomo/mihomo") or "/opt/mihomo/mihomo"
    geodata_dir = Path(getenv("GEODATA_DIR", str(output_path.parent)) or str(output_path.parent))
    geoip_path = geodata_dir / "geoip.metadb"
    geoip_url = getenv(
        "GEOIP_URL",
        "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb",
    ) or "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb"
    validate_timeout = int(getenv("VALIDATE_TIMEOUT", "180") or "180")
    controller_url = getenv("CONTROLLER_URL", "http://127.0.0.1:9090")
    controller_secret = getenv("CONTROLLER_SECRET", "")
    service_name = getenv("SERVICE_NAME", "mihomo.service") or "mihomo.service"
    restart_on_reload_fail = (getenv("RESTART_ON_RELOAD_FAIL", "1") or "1") == "1"

    log(f"fetching subscription with UA {user_agent!r}")
    raw_text, headers = fetch_subscription(subscription_url, user_agent, request_timeout)
    log(f"subscription response headers captured: {len(headers)} entries")

    subscription = validate_yaml_mapping(raw_text)
    dump_yaml(cache_path, subscription)
    log(f"saved raw subscription to {cache_path}")

    override = load_yaml_file(override_path)
    prepend_rules = override.pop("prepend-rules", []) or []
    append_rules = override.pop("append-rules", []) or []

    if not isinstance(prepend_rules, list) or not isinstance(append_rules, list):
        raise RuntimeError("prepend-rules and append-rules must be YAML lists")

    merged = deep_merge(subscription, override)

    rules = list(merged.get("rules") or [])
    merged["rules"] = list(prepend_rules) + rules + list(append_rules)

    if any(isinstance(rule, str) and rule.startswith("GEOIP,") for rule in merged["rules"]):
        if not geoip_path.exists() or geoip_path.stat().st_size == 0:
            log(f"downloading GeoIP database to {geoip_path}")
            download_file(geoip_url, geoip_path, geodata_timeout)
        else:
            log(f"reusing existing GeoIP database at {geoip_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(output_path.parent),
        prefix=f"{output_path.name}.",
        suffix=".new",
        delete=False,
    ) as handle:
        temp_output = Path(handle.name)
        yaml.safe_dump(
            merged,
            handle,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

    try:
        test_config(mihomo_bin, geodata_dir, temp_output, validate_timeout)

        if output_path.exists():
            shutil.copy2(output_path, backup_path)
            log(f"backed up current config to {backup_path}")

        temp_output.replace(output_path)
        log(f"installed merged config to {output_path}")

        if controller_url and controller_secret:
            try:
                reload_controller(controller_url, controller_secret, output_path, request_timeout)
                log("mihomo config reload completed through controller API")
            except Exception as exc:
                log(f"controller reload failed: {exc}")
                if restart_on_reload_fail:
                    maybe_restart_service(service_name)
                else:
                    raise
        else:
            log("controller reload skipped because controller URL or secret is empty")
    finally:
        if temp_output.exists():
            temp_output.unlink()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        log(f"HTTP error while fetching subscription: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        log(f"network error while fetching subscription: {exc.reason}")
    except Exception as exc:
        log(f"update failed: {exc}")
    raise SystemExit(1)
