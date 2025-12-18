# Docker Compose MySQL Backup

This tool parses your `docker-compose.yml` to find MySQL/MariaDB services, locates their running containers, inspects credentials, lists user databases, and dumps each database via `docker exec` to timestamped `.sql` files.

## Requirements
- Docker Desktop with Compose v2 (`docker compose ...` commands)
- Containers must be running
- MySQL credentials must be available in container environment (e.g., `MYSQL_ROOT_PASSWORD`, or `MYSQL_USER` + `MYSQL_PASSWORD`)

## Usage (Windows PowerShell)

From the project directory containing your compose file:

```powershell
# Change to the folder that has docker-compose.yml
Set-Location "C:\path\to\your\project"

# Run the backup script from the vps-backups workspace
python "C:\Users\ryanm\OneDrive\Documents\vps-backups\compose_backup.py" -f .\docker-compose.yml -o "C:\Users\ryanm\OneDrive\Documents\vps-backups\backups"
```

Options:
- `-f/--compose`: path to `docker-compose.yml` (default: `./docker-compose.yml`)
- `-o/--out`: output directory for dumps (default: `./backups`)
- `-s/--service`: limit to specific service(s); can repeat

## What it backs up
- Lists databases with `SHOW DATABASES;` inside each container
- Excludes system DBs: `information_schema`, `performance_schema`, `mysql`, `sys`
- Dumps each remaining database individually using:
  - `mysqldump --single-transaction --quick --lock-tables=false`
- Writes one `.sql` per database directly to your chosen output directory
- Deduplicates by database name across services/containers (first match wins)

## Volume Backups
- Detects mounts for detected MySQL/MariaDB services via `docker inspect .Mounts`
- Backs up both named volumes and bind mounts:
  - Named volumes: archived via `docker run --rm -v <vol>:/_backup_src busybox tar -C /_backup_src -czf - .`
  - Bind mounts: archived via `docker run --rm -v <host_path>:/_backup_src busybox tar -C /_backup_src -czf - .`
- Deduplicates by volume name (for volumes) and host path (for binds)
- Output files:
  - `volume__<name>.tar.gz` for named volumes
  - `bind__<normalized-host-path>.tar.gz` for bind mounts

## Output Directory Structure
```
backups/
├── docker-compose.yml
├── docker-dir.tar.gz        (optional, if --docker-dir is provided)
├── db/
│   ├── database1.sql
│   ├── database2.sql
│   └── ...
└── volumes/
    ├── volume__myvolume.tar.gz
    ├── bind__host_path.tar.gz
    └── ...
```

## Optional Parameters
- `--docker-dir` / `-d`: Path to a Docker directory to backup and compress (e.g., `/opt/docker`). If provided, a `docker-dir.tar.gz` file will be created in the output directory.

## Notes
- If `MYSQL_ROOT_PASSWORD` exists, root is used; otherwise uses `MYSQL_USER` + `MYSQL_PASSWORD`.
- For stacks using MariaDB, `MARIADB_*` env vars are supported similarly.
- If no containers are running for detected services, you'll see a warning.

## Deploy to Debian Server (remote)

Prereqs on the server:
- `docker` and Compose v2 installed (`docker compose --help`)
- `python3` available

1) Copy the Python script to the server (from Windows):

```powershell
# Replace host, user, and destination path
scp C:\Users\ryanm\OneDrive\Documents\vps-backups\compose_backup.py user@host:~/compose-mysql-backup/
```

2) On the server, make it executable and run a test:

```bash
ssh user@host << 'EOF'
set -e
cd ~/compose-mysql-backup
chmod +x compose_backup.py
# Example run: adjust paths to your compose file and desired output directory
./compose_backup.py -f /srv/app/docker-compose.yml -o /var/backups/docker-mysql
EOF
```

3) Optional: limit to specific services

```bash
./compose_backup.py -f /srv/app/docker-compose.yml -o /var/backups/docker-mysql -s db -s mariadb
```

4) Schedule with cron (daily at 02:15):

```bash
sudo bash -c 'cat > /etc/cron.d/compose-mysql-backup <<CRON
# m h dom mon dow user  command
15 2 * * * root /home/user/compose-mysql-backup/compose_backup.py -f /srv/app/docker-compose.yml -o /var/backups/docker-mysql >> /var/log/compose-mysql-backup.log 2>&1
CRON'
```

Backups will be written under `/var/backups/docker-mysql/` with one `.sql` per database name.
