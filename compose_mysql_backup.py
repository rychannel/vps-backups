#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from typing import Set

SYSTEM_DATABASES = {
    "information_schema",
    "performance_schema",
    "mysql",
    "sys",
}


def run_cmd(cmd: List[str]) -> Tuple[int, str, str]:
    """Run a command and return (code, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)


def compose_config_json(compose_file: Path) -> Optional[Dict]:
    """Get normalized compose config as JSON using docker compose CLI."""
    code, out, err = run_cmd(["docker", "compose", "-f", str(compose_file), "config", "--format", "json"])
    if code != 0:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def find_mysql_services(config: Dict) -> List[str]:
    services = config.get("services", {})
    mysql_services = []
    for name, svc in services.items():
        image = (svc.get("image") or "").lower()
        env = svc.get("environment") or {}
        is_mysql = (
            "mysql" in image or "mariadb" in image or
            any(k.upper().startswith("MYSQL_") for k in (env.keys() if isinstance(env, dict) else env))
        )
        if is_mysql:
            mysql_services.append(name)
    return mysql_services


def compose_ps_json(compose_file: Path) -> Optional[List[Dict]]:
    code, out, err = run_cmd(["docker", "compose", "-f", str(compose_file), "ps", "--format", "json"])
    if code != 0:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def map_services_to_containers(compose_file: Path, target_services: List[str]) -> Dict[str, List[str]]:
    """Return {service: [container_names]} mapping."""
    mapping: Dict[str, List[str]] = {s: [] for s in target_services}

    # Try compose ps first
    ps = compose_ps_json(compose_file)
    if isinstance(ps, list):
        for item in ps:
            svc = item.get("Service") or item.get("service")
            name = item.get("Name") or item.get("name")
            if svc in mapping and name:
                mapping[svc].append(name)

    # Fallback: docker ps with compose labels
    remaining = [s for s, names in mapping.items() if not names]
    if remaining:
        code, out, err = run_cmd(["docker", "ps", "--format", "{{json .}}"])
        if code == 0:
            for line in out.splitlines():
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                labels = (obj.get("Labels") or "")
                name = obj.get("Names") or obj.get("Name")
                for svc in list(remaining):
                    label_kv = f"com.docker.compose.service={svc}"
                    if label_kv in labels and name:
                        mapping[svc].append(name)
                        remaining.remove(svc)
                        break

    return mapping


def inspect_env(container: str) -> Dict[str, str]:
    code, out, err = run_cmd(["docker", "inspect", "--format", "{{json .Config.Env}}", container])
    env_map: Dict[str, str] = {}
    if code != 0:
        return env_map
    try:
        env_list = json.loads(out)
    except json.JSONDecodeError:
        env_list = []
    for item in env_list:
        if isinstance(item, str) and "=" in item:
            k, v = item.split("=", 1)
            env_map[k] = v
    return env_map


def resolve_mysql_credentials(env: Dict[str, str]) -> Optional[Tuple[str, str]]:
    # Prefer root where available
    root_pass = env.get("MYSQL_ROOT_PASSWORD") or env.get("MARIADB_ROOT_PASSWORD")
    if root_pass:
        return ("root", root_pass)
    user = env.get("MYSQL_USER") or env.get("MARIADB_USER") or env.get("MYSQL_USERNAME")
    pwd = env.get("MYSQL_PASSWORD") or env.get("MARIADB_PASSWORD")
    if user and pwd:
        return (user, pwd)
    return None


def list_databases(container: str, user: str, password: str) -> List[str]:
    sql = "SHOW DATABASES;"
    cmd = [
        "docker", "exec", container,
        "mysql", "-N", "-u", user, f"-p{password}",
        "-e", sql,
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        return []
    dbs = [line.strip() for line in out.splitlines() if line.strip()]
    return [d for d in dbs if d not in SYSTEM_DATABASES]


def dump_database(container: str, db: str, user: str, password: str) -> Optional[bytes]:
    cmd = [
        "docker", "exec", container,
        "mysqldump", "--single-transaction", "--quick", "--lock-tables=false",
        "-u", user, f"-p{password}", db,
    ]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False, check=False)
    except FileNotFoundError:
        return None
    if p.returncode != 0:
        return None
    return p.stdout


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def backup_service_containers(service: str, containers: List[str], out_dir: Path, seen_dbs: Set[str]) -> Dict[str, List[str]]:
    results: Dict[str, List[str]] = {service: []}
    for container in containers:
        env = inspect_env(container)
        creds = resolve_mysql_credentials(env)
        if not creds:
            print(f"[WARN] {container}: No MySQL credentials found in environment; skipping.")
            continue
        user, pwd = creds
        dbs = list_databases(container, user, pwd)
        if not dbs:
            print(f"[WARN] {container}: No user databases found; skipping.")
            continue
        for db in dbs:
            if db in seen_dbs:
                print(f"[SKIP] Duplicate database '{db}' already dumped; skipping {container}.")
                continue
            dump = dump_database(container, db, user, pwd)
            if dump is None:
                print(f"[ERROR] {container}: Failed to dump {db}.")
                continue
            filename = out_dir / f"{db}.sql"
            with open(filename, "wb") as f:
                f.write(dump)
            seen_dbs.add(db)
            results[service].append(str(filename))
            print(f"[OK] Saved {db} -> {filename}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Backup MySQL/MariaDB databases from Docker Compose services.")
    parser.add_argument("--compose", "-f", type=Path, default=Path("docker-compose.yml"), help="Path to docker-compose.yml")
    parser.add_argument("--out", "-o", type=Path, default=Path("backups"), help="Output directory for SQL dumps")
    parser.add_argument("--service", "-s", action="append", help="Limit backup to specific service(s)")
    args = parser.parse_args()

    compose_file: Path = args.compose
    out_root: Path = args.out

    if not compose_file.exists():
        print(f"[ERROR] Compose file not found: {compose_file}")
        raise SystemExit(2)

    config = compose_config_json(compose_file)
    if not config:
        print("[ERROR] Failed to load Compose config (JSON). Ensure Docker Desktop and Compose v2 are installed.")
        raise SystemExit(2)

    mysql_services = find_mysql_services(config)
    if args.service:
        mysql_services = [s for s in mysql_services if s in set(args.service)]
        if not mysql_services:
            print("[ERROR] No matching MySQL services after applying --service filter.")
            raise SystemExit(2)

    if not mysql_services:
        print("[ERROR] No MySQL/MariaDB services detected in compose file.")
        raise SystemExit(2)

    mapping = map_services_to_containers(compose_file, mysql_services)

    # Write directly to the provided output directory and deduplicate by DB name
    out_dir = out_root
    ensure_dir(out_dir)
    seen_dbs: Set[str] = set()

    summary: Dict[str, List[str]] = {}
    for svc, containers in mapping.items():
        if not containers:
            print(f"[WARN] No running containers for service '{svc}'. Is the stack up?")
            continue
        res = backup_service_containers(svc, containers, out_dir, seen_dbs)
        summary.update(res)

    print("\n=== Backup Summary ===")
    for svc, files in summary.items():
        print(f"Service: {svc}")
        for f in files:
            print(f" - {f}")
    print(f"Output directory: {out_dir}")


if __name__ == "__main__":
    main()
