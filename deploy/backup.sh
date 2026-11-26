#!/usr/bin/env bash
# Nightly encrypted backup of the database and the encrypted file store.
# Install: sudo cp deploy/backup.sh /usr/local/bin/csp-backup && sudo chmod 700 /usr/local/bin/csp-backup
# Cron (as root): 30 2 * * * /usr/local/bin/csp-backup
# The backup passphrase lives in /etc/csp-backup.pass (chmod 600, root only). Store a copy offline too.
set -euo pipefail

BACKUP_DIR=/srv/csp-onboarding/backups
DATA_DIR=/srv/csp-onboarding/data
DB=csp_onboarding
KEEP_DAYS=30
STAMP=$(date +%Y%m%d-%H%M)

mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"

sudo -u postgres pg_dump -Fc "$DB" \
  | gpg --batch --symmetric --cipher-algo AES256 --passphrase-file /etc/csp-backup.pass \
  > "$BACKUP_DIR/db-$STAMP.dump.gpg"

tar -C "$DATA_DIR" -cf - objects \
  | gpg --batch --symmetric --cipher-algo AES256 --passphrase-file /etc/csp-backup.pass \
  > "$BACKUP_DIR/files-$STAMP.tar.gpg"

find "$BACKUP_DIR" -name '*.gpg' -mtime +"$KEEP_DAYS" -delete

# Copy off the server (second location in India), e.g.:
# rsync -a "$BACKUP_DIR/" backup-user@backup-host:/backups/csp-onboarding/
echo "backup $STAMP done"
