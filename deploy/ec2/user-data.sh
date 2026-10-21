#!/bin/bash
# Common Ground on one Amazon Linux 2023 (x86_64) instance. Python serves the app on 127.0.0.1:8761 and
# Caddy, in front of it, gets and renews a Let's Encrypt certificate for <public IPv4, dashes>.nip.io and
# serves the site over HTTPS. There is no plain-HTTP mode: the person gate needs HTTPS.
#
# Paste the whole file into the launch wizard's Advanced details > User data. The only line you edit is
# the QLOO_API_KEY line, and only when PROVIDER is live. The committed file never holds a key. AWS runs
# user data once, as root, on first boot, and keeps a copy of the script on the instance.
set -euo pipefail

QLOO_API_KEY=            # <<< the one line to edit: with PROVIDER=live, type the Qloo key straight after the =
PROVIDER=fake            # fake: the sample source, no key, and the page says so. live: calls Qloo, needs the key
DAILY_LIVE_CALLS=300     # most live Qloo calls this server makes in a day; lower it if the key's email says to
REPO_URL=https://github.com/guptachetan1995/common-ground
REF=main                 # a branch, a tag or a commit of that repository
DNS_NAME=nip.io          # sslip.io is the same service under its other name, if Let's Encrypt limits this one
CADDY_VERSION=2.11.7
CADDY_SHA512=a7a433a1b133efc3c8d10eb0b99d52a24b5ef5c322dc77f5282182b1c0402139ab83f3a99f0c52409df77d20123fb0b523edad8a66d8f5e49136197bf61ef0e7
APP_PORT=8761
CERT_WAIT_S=600
PYTHON=/usr/bin/python3.13

note() {
  local line
  line="$(date -u +%H:%M:%S) common-ground: $*"
  echo "$line" >&2
  { echo "$line" > /dev/console; } 2> /dev/null || true
}

die() {
  note "$*"
  exit 1
}

check_settings() {
  case "$PROVIDER" in
    live | fake) ;;
    *) die "PROVIDER must be live or fake. Nothing was installed." ;;
  esac
  case "$QLOO_API_KEY" in
    *' '* | *$'\t'* | *$'\r'* | *'"'* | *"'"* | *'\'*)
      die "The key line holds a space, a quote or a backslash. Type the key alone after the =. Nothing was installed." ;;
  esac
  if [ "$PROVIDER" = live ] && [ -z "$QLOO_API_KEY" ]; then
    die "PROVIDER is live and the QLOO_API_KEY line is empty. Nothing was installed. Launch again with the key typed in, or with PROVIDER=fake."
  fi
  if [ "$PROVIDER" = fake ] && [ -n "$QLOO_API_KEY" ]; then
    note "PROVIDER is fake, so the key is ignored and is not copied onto this instance (AWS still keeps the script as pasted)."
  fi
}

public_name() {
  local token ip=
  token="$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300')"
  for _ in $(seq 1 12); do
    ip="$(curl -fsS -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
    if [[ "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
      echo "${ip//./-}.$DNS_NAME"
      return
    fi
    sleep 5
  done
  die "This instance has no public IPv4 address. Auto-assign public IP must be Enable in the launch wizard."
}

install_app() {
  install -d /opt/common-ground
  curl -fsSL "$REPO_URL/archive/$REF.tar.gz" | tar -xz -C /opt/common-ground --strip-components=1
  [ -f /opt/common-ground/common_ground/__main__.py ] || die "The download from $REPO_URL at $REF holds no common_ground package."
  useradd --system --no-create-home --shell /sbin/nologin commonground
  ( umask 077
    {
      printf 'COMMON_GROUND_PROVIDER=%s\n' "$PROVIDER"
      printf 'COMMON_GROUND_BIND=127.0.0.1\n'
      printf 'COMMON_GROUND_PORT=%s\n' "$APP_PORT"
      printf 'COMMON_GROUND_ALLOWED_HOSTS=%s\n' "$HOST"
      printf 'COMMON_GROUND_TRUST_PROXY=1\n'
      printf 'COMMON_GROUND_DAILY_LIVE_CALLS=%s\n' "$DAILY_LIVE_CALLS"
      if [ "$PROVIDER" = live ]; then printf 'QLOO_API_KEY=%s\n' "$QLOO_API_KEY"; fi
    } > /etc/common-ground.env )
  cat > /etc/systemd/system/common-ground.service <<UNIT
[Unit]
Description=Common Ground
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
User=commonground
Group=commonground
WorkingDirectory=/opt/common-ground
EnvironmentFile=/etc/common-ground.env
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON -m common_ground serve
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
UNIT
}

install_caddy() {
  local archive=/tmp/caddy.tar.gz
  curl -fsSLo "$archive" "https://github.com/caddyserver/caddy/releases/download/v$CADDY_VERSION/caddy_${CADDY_VERSION}_linux_amd64.tar.gz"
  echo "$CADDY_SHA512  $archive" | sha512sum -c - > /dev/null ||
    die "The Caddy download does not match the SHA-512 in this script. Nothing was started."
  tar -xzf "$archive" -C /usr/local/bin caddy
  chmod 755 /usr/local/bin/caddy
  rm -f "$archive"
  useradd --system --create-home --home-dir /var/lib/caddy --shell /sbin/nologin caddy
  install -d /etc/caddy
  cat > /etc/caddy/Caddyfile <<CADDYFILE
$HOST {
	reverse_proxy 127.0.0.1:$APP_PORT {
		request_buffers 64KB
	}
}
CADDYFILE
  cat > /etc/systemd/system/caddy.service <<'UNIT'
[Unit]
Description=Caddy
Wants=network-online.target
After=network-online.target common-ground.service

[Service]
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --environ --config /etc/caddy/Caddyfile
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
UNIT
}

app_answers() {
  [ "$(curl -fsS --max-time 3 "http://127.0.0.1:$APP_PORT/healthz" || true)" = ok ]
}

certificate_answers() {
  [ "$(curl -fsS --max-time 10 --resolve "$HOST:443:127.0.0.1" "https://$HOST/healthz" || true)" = ok ]
}

check_settings
note "Settings accepted (provider $PROVIDER). Installing Python 3.13: Amazon's package, since /usr/bin/python3 stays 3.9."
dnf install -y tar gzip python3.13 || die "dnf could not install python3.13. Nothing else was installed."
note "$("$PYTHON" --version) at $PYTHON"

HOST="$(public_name)"
note "The site will be https://$HOST/"

install_app
install_caddy
systemctl daemon-reload
systemctl enable --now common-ground.service caddy.service

for _ in $(seq 1 30); do app_answers && break; sleep 1; done
app_answers || die "The app does not answer on 127.0.0.1:$APP_PORT. Its own lines are above in this log."
note "The app answers on 127.0.0.1:$APP_PORT (provider $PROVIDER). Waiting for the certificate."

SECONDS=0
until certificate_answers; do
  if [ "$SECONDS" -ge "$CERT_WAIT_S" ]; then
    die "No certificate after $SECONDS seconds. Caddy keeps retrying and its own lines are above. The name is https://$HOST/"
  fi
  sleep 10
done
note "Certificate ready after $SECONDS seconds: https://$HOST/ (python3.13, Caddy $CADDY_VERSION with the SHA-512 matched, provider $PROVIDER)"
