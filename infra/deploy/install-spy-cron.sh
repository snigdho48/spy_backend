#!/usr/bin/env bash
# Install a user crontab entry that runs spy-watcher.sh at 01:00 Asia/Dhaka.
set -euo pipefail

APP_DIR="${SPY_APP_DIR:-$HOME/apps/spy-backend}"
WATCHER="$APP_DIR/infra/deploy/spy-watcher.sh"
BEGIN="# BEGIN spy-backend-watcher"
END="# END spy-backend-watcher"

if [[ ! -f "$WATCHER" ]]; then
  echo "ERROR: ${WATCHER} is missing. Run deploy-spy.sh first so the checkout exists." >&2
  exit 1
fi
if ! command -v crontab >/dev/null 2>&1; then
  echo "ERROR: crontab is missing. On the TX6: sudo apt-get install cron" >&2
  exit 1
fi

chmod +x "$WATCHER" "$APP_DIR/infra/deploy/deploy-spy.sh"

tz="unknown"
if command -v timedatectl >/dev/null 2>&1; then
  tz="$(timedatectl show -p Timezone --value 2>/dev/null || echo unknown)"
elif [[ -f /etc/timezone ]]; then
  tz="$(tr -d '[:space:]' </etc/timezone)"
fi

if [[ "$tz" != "Asia/Dhaka" ]]; then
  cat >&2 <<EOF
WARNING: system timezone is '${tz}', not Asia/Dhaka.

Ubuntu 24.04 and Armbian ship Debian cron. It fires jobs in the system
timezone and ignores CRON_TZ (that variable is a cronie feature). With the
system clock left on UTC, '0 1 * * *' is 01:00 UTC, which is 07:00 in Dhaka.
01:00 Asia/Dhaka is 19:00 UTC the previous evening (UTC+6, no daylight saving).

To make 01:00 mean 01:00 in Dhaka:

  sudo timedatectl set-timezone Asia/Dhaka

The crontab still sets CRON_TZ=Asia/Dhaka (honored on cronie, and on Debian
cron it is only an environment variable). The job also sets TZ=Asia/Dhaka so
the watcher process formats timestamps in Dhaka. TZ does not change when
Debian cron starts the job.
EOF
fi

block="$(cat <<EOF
$BEGIN
# Spy Love updater. 01:00 in the system timezone; see infra/deploy/README.md.
CRON_TZ=Asia/Dhaka
0 1 * * * TZ=Asia/Dhaka /bin/bash "$WATCHER"
$END
EOF
)"

current="$(crontab -l 2>/dev/null || true)"
filtered="$(printf '%s\n' "$current" | awk -v b="$BEGIN" -v e="$END" '
  $0 == b { skip = 1; next }
  $0 == e { skip = 0; next }
  skip != 1 { print }
')"

{
  printf '%s\n' "$filtered" | sed '/./,$!d'
  printf '\n%s\n' "$block"
} | crontab -

echo "Installed a user crontab entry for ${WATCHER}."
crontab -l | awk -v b="$BEGIN" -v e="$END" '$0==b{s=1} s{print} $0==e{s=0}'
