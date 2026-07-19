"""
Kerno — resilience infrastructure: kerno.db backup with rotation.

Not a one-off fix. This is the permanent answer to the disk-full/lost-folder
incident: kerno.db (irreplaceable tick data) must never live as a single copy
on a single machine again.

What this does:
  1. Copies kerno.db to a timestamped backup in BACKUP_DIR.
  2. Keeps the last KEEP_LAST backups, deletes older ones (rotation — avoids
     silently filling the disk again with backups of a backup).
  3. Prints total backup storage used, so disk pressure is visible before it
     becomes a crisis again.

Usage:
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\backup_kerno_db.py

Recommended: run this before any risky operation (schema migration, bulk
delete) and on a regular cadence (e.g. daily, via Windows Task Scheduler).
"""

import os
import shutil
import time

DB_PATH = "kerno.db"
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)) or ".", "backups")
KEEP_LAST = 2  # rotation: kerno.db grows with each new exchange (2.5GB+ already) —
               # 2 backups is the ceiling this disk can safely absorb right now.
               # Re-evaluate KEEP_LAST whenever kerno.db size or free disk space changes materially.


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found in current directory. Run this from the project root.")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_name = f"kerno_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    src_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"Backing up {DB_PATH} ({src_size_mb:.1f} MB) -> {backup_path}")

    shutil.copy2(DB_PATH, backup_path)
    print("Backup complete.")

    # Rotation: list backups, delete oldest beyond KEEP_LAST
    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith("kerno_") and f.endswith(".db")]
    )
    if len(backups) > KEEP_LAST:
        to_delete = backups[:-KEEP_LAST]
        for old in to_delete:
            old_path = os.path.join(BACKUP_DIR, old)
            os.remove(old_path)
            print(f"Rotated out old backup: {old}")

    # Report total backup storage used, so this doesn't silently become the
    # next disk-full incident
    remaining = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith("kerno_") and f.endswith(".db")]
    )
    total_size_mb = sum(
        os.path.getsize(os.path.join(BACKUP_DIR, f)) for f in remaining
    ) / (1024 * 1024)
    print(f"\nBackups retained: {len(remaining)} (keeping last {KEEP_LAST})")
    print(f"Total backup storage: {total_size_mb:.1f} MB in {BACKUP_DIR}")

    # Disk space check — surface the problem before it repeats
    total, used, free = shutil.disk_usage(os.path.dirname(os.path.abspath(DB_PATH)) or ".")
    free_gb = free / (1024 ** 3)
    projected_full_rotation_gb = (src_size_mb / 1024) * KEEP_LAST
    print(f"Free disk space on this drive: {free_gb:.2f} GB")
    print(f"Projected space needed at full rotation ({KEEP_LAST} backups): {projected_full_rotation_gb:.2f} GB")
    if free_gb < 5:
        print("WARNING: free disk space below 5GB. Address this before running further migrations.")
    if free_gb < projected_full_rotation_gb:
        print(
            f"WARNING: current free space ({free_gb:.2f} GB) is less than what full backup "
            f"rotation will require ({projected_full_rotation_gb:.2f} GB). This backup system "
            f"could cause the next disk-full incident. Move backups off this drive (cloud/external) "
            f"or lower KEEP_LAST before relying on this."
        )


if __name__ == "__main__":
    main()
