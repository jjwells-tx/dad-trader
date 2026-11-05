#!/bin/bash
# One-shot installer for the rung sheet on a RHEL 8/9 EC2 instance.
#
#   unzip dad-trader.zip && cd dad-trader && bash deploy/install.sh [--https you@example.com] [--key service-account.json]
#
# What it does:
#   1. installs Python 3.11 and tools          5. password-protects the site (asks you for passwords)
#   2. copies the app to /opt/dad-trader       6. schedules refreshes at 8:30, 12:00, 3:15 CT on weekdays
#   3. builds the database from the sheets     7. (with --https) gets a Let's Encrypt certificate
#   4. publishes the rung sheet to the site
# With --key, the Google service account key is stored in /etc/dad-trader/ and every refresh pulls Dad's
# sheets straight from Google Sheets. Without it, the CSV exports in data/sheets/ are used (or a key
# installed by an earlier run).
# It also asks for a Gemini API key (once) and runs the AI chat backend as the dad-trader-chat service on
# 127.0.0.1:8001; the web server passes /chat to it behind the same password login.
# Safe to re-run: it updates the code and keeps the existing database settings, passwords and key.
set -euo pipefail

APP=/opt/dad-trader
DOMAIN=trader.wellslabs.dev
KEY_DIR=/etc/dad-trader
KEY=$KEY_DIR/service-account.json
HTTPS_EMAIL=""
KEY_SRC=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --https) HTTPS_EMAIL="${2:?give an email after --https}"; shift 2 ;;
    --key)   KEY_SRC="${2:?give the service account JSON file after --key}"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done
[[ -n "$KEY_SRC" && ! -f "$KEY_SRC" ]] && { echo "No such key file: $KEY_SRC"; exit 1; }
[[ -n "$KEY_SRC" ]] && KEY_SRC="$(cd "$(dirname "$KEY_SRC")" && pwd)/$(basename "$KEY_SRC")"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Checking the web server"
if systemctl is-active --quiet nginx; then WEB=nginx; WEBROOT=/usr/share/nginx/html; WEBUSER=nginx
elif systemctl is-active --quiet httpd; then WEB=httpd; WEBROOT=/var/www/html; WEBUSER=apache
else echo "Neither nginx nor httpd is running. Start the one serving the placeholder page and re-run."; exit 1; fi
echo "Found $WEB, web root $WEBROOT"

say "Setting the clock to Central time"
sudo timedatectl set-timezone America/Chicago

say "Installing packages"
sudo dnf install -y -q python3.11 python3.11-pip unzip httpd-tools cronie tar
sudo systemctl enable --now crond

say "Copying the app to $APP"
sudo mkdir -p "$APP"
tar -C "$SRC" --exclude=./.venv --exclude='./data/*.db' --exclude='./data/*.json' --exclude='./*.json' --exclude=./out --exclude=./.git -cf - . | sudo tar -C "$APP" -xf -
sudo chown -R "$USER": "$APP"
cd "$APP"
python3.11 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt yfinance google-auth requests

say "Running tests"
python -m pytest -q

if [[ -n "$KEY_SRC" ]]; then
  say "Installing the Google service account key in $KEY_DIR"
  sudo mkdir -p "$KEY_DIR"
  sudo install -m 600 -o "$USER" "$KEY_SRC" "$KEY"
  sudo chmod 700 "$KEY_DIR" && sudo chown "$USER": "$KEY_DIR"
fi

say "Building the database from the sheets"
if [[ -f "$KEY" ]]; then
  python -m trader sync --key "$KEY" || { echo "WARN: Google Sheets sync failed; using the CSV exports"; python -m trader seed; }
else
  echo "No service account key; using the CSV exports in data/sheets/"
  python -m trader seed
fi

say "Writing the publish script"
cat > "$APP/publish.sh" <<EOF
#!/bin/bash
# Pull Dad's sheets, refresh prices, rebuild the rung sheet, and put it on the site.
set -uo pipefail
cd $APP
source .venv/bin/activate
if [[ -f $KEY ]]; then
  python -m trader sync --key $KEY || echo "WARN: Google Sheets sync failed; using the last synced positions"
fi
python -m trader prices --yahoo || echo "WARN: live prices failed; using the last stored prices"
python -m trader rungs || exit 1
sudo cp "out/rung-sheet-\$(date +%F).html" $WEBROOT/index.html
sudo cp "out/orders-\$(date +%F).csv" $WEBROOT/orders.csv
sudo restorecon -R $WEBROOT 2>/dev/null || true
echo "Published \$(date '+%F %H:%M')"
EOF
chmod +x "$APP/publish.sh"
mkdir -p "$APP/out"

say "Publishing the first rung sheet"
"$APP/publish.sh"

say "Setting up the AI chat"
GEMINI_ENV=$KEY_DIR/gemini.env
sudo mkdir -p "$KEY_DIR" && sudo chown "$USER": "$KEY_DIR" && sudo chmod 700 "$KEY_DIR"
if [[ ! -s "$GEMINI_ENV" ]]; then
  echo "Paste a Gemini API key from https://aistudio.google.com/apikey (input hidden; leave blank to skip the chat for now):"
  read -rs GEMINI_KEY; echo
  if [[ -n "$GEMINI_KEY" ]]; then
    ( umask 077; printf 'GEMINI_API_KEY=%s\n' "$GEMINI_KEY" > "$GEMINI_ENV" )
  else
    echo "Skipped. The page still works; the chat will say it isn't set up. Re-run this script to add a key."
  fi
  unset GEMINI_KEY
else
  echo "Keeping the existing Gemini key in $GEMINI_ENV (delete it and re-run to change it)"
fi
sudo tee /etc/systemd/system/dad-trader-chat.service >/dev/null <<EOF
[Unit]
Description=Rung sheet AI chat backend
After=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP
EnvironmentFile=-$GEMINI_ENV
ExecStart=$APP/.venv/bin/python -m trader serve --host 127.0.0.1 --port 8001
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q dad-trader-chat
sudo systemctl restart dad-trader-chat
# SELinux blocks the web server from connecting to local ports unless this is on
sudo setsebool -P httpd_can_network_connect 1 2>/dev/null || true

say "Password-protecting the site"
if [[ ! -s /etc/trader.htpasswd ]]; then
  echo "Choose a password for user 'dad':"
  sudo htpasswd -c /etc/trader.htpasswd dad
  echo "Choose a password for user 'jeff':"
  sudo htpasswd /etc/trader.htpasswd jeff
else
  echo "Keeping existing passwords in /etc/trader.htpasswd (add users with: sudo htpasswd /etc/trader.htpasswd NAME)"
fi
sudo chgrp "$WEBUSER" /etc/trader.htpasswd && sudo chmod 640 /etc/trader.htpasswd

if [[ $WEB == nginx ]]; then
  # RHEL's stock nginx.conf includes default.d/*.conf inside the default server block
  if grep -q "default.d/\*.conf" /etc/nginx/nginx.conf; then
    printf 'auth_basic "Rung Sheet";\nauth_basic_user_file /etc/trader.htpasswd;\n' | sudo tee /etc/nginx/default.d/trader-auth.conf >/dev/null
    # /chat goes to the Python backend; it inherits the password login above
    printf 'location = /chat {\n    proxy_pass http://127.0.0.1:8001;\n    proxy_set_header Host $host;\n    proxy_set_header X-Forwarded-Host $host;\n    proxy_read_timeout 120s;\n    client_max_body_size 64k;\n}\n' \
      | sudo tee /etc/nginx/default.d/trader-chat.conf >/dev/null
  else
    echo "WARN: couldn't find where to add the password lines. Add these two lines inside your server { } block:"
    echo '  auth_basic "Rung Sheet";'; echo '  auth_basic_user_file /etc/trader.htpasswd;'
    echo "  and: location = /chat { proxy_pass http://127.0.0.1:8001; proxy_set_header X-Forwarded-Host \$host; proxy_read_timeout 120s; }"
  fi
  sudo nginx -t && sudo systemctl reload nginx
else
  # certbot --apache needs a port-80 virtual host that names the domain
  if ! grep -rqs "ServerName $DOMAIN" /etc/httpd/conf.d/; then
    sudo tee /etc/httpd/conf.d/trader.conf >/dev/null <<EOF
<VirtualHost *:80>
    ServerName $DOMAIN
    DocumentRoot $WEBROOT
</VirtualHost>
EOF
  fi
  sudo tee /etc/httpd/conf.d/trader-auth.conf >/dev/null <<EOF
<Directory "$WEBROOT">
    AuthType Basic
    AuthName "Rung Sheet"
    AuthUserFile /etc/trader.htpasswd
    Require valid-user
</Directory>

# /chat goes to the Python backend, behind the same login
ProxyTimeout 120
<Location "/chat">
    ProxyPass "http://127.0.0.1:8001/chat"
    ProxyPassReverse "http://127.0.0.1:8001/chat"
    ProxyPreserveHost On
    AuthType Basic
    AuthName "Rung Sheet"
    AuthUserFile /etc/trader.htpasswd
    Require valid-user
</Location>
EOF
  sudo apachectl configtest && sudo systemctl reload httpd
fi

say "Scheduling refreshes (weekdays 8:30, 12:00, 3:15 Central)"
( crontab -l 2>/dev/null | grep -v "$APP/publish.sh" || true
  echo "30 8  * * 1-5 $APP/publish.sh >> $APP/out/cron.log 2>&1"
  echo "0  12 * * 1-5 $APP/publish.sh >> $APP/out/cron.log 2>&1"
  echo "15 15 * * 1-5 $APP/publish.sh >> $APP/out/cron.log 2>&1" ) | crontab -
crontab -l | grep publish.sh

if [[ -n "$HTTPS_EMAIL" ]]; then
  say "Getting an HTTPS certificate for $DOMAIN"
  RHEL=$(rpm -E %rhel)
  rpm -q epel-release >/dev/null 2>&1 || sudo dnf install -y -q "https://dl.fedoraproject.org/pub/epel/epel-release-latest-${RHEL}.noarch.rpm"
  if [[ $WEB == nginx ]]; then sudo dnf install -y -q certbot python3-certbot-nginx; PLUG=--nginx
  else sudo dnf install -y -q certbot python3-certbot-apache mod_ssl; PLUG=--apache; fi
  sudo certbot $PLUG -d "$DOMAIN" -m "$HTTPS_EMAIL" --agree-tos --non-interactive --redirect
  sudo systemctl enable --now certbot-renew.timer 2>/dev/null || true
fi

say "Done"
echo "Rung sheet: http${HTTPS_EMAIL:+s}://$DOMAIN  (users: dad, jeff)"
echo "Refresh by hand any time: $APP/publish.sh     Log: $APP/out/cron.log"
echo "AI chat backend: sudo systemctl status dad-trader-chat     Log: journalctl -u dad-trader-chat"
[[ -z "$HTTPS_EMAIL" ]] && echo "Not on HTTPS yet — passwords travel unencrypted. Re-run with: bash deploy/install.sh --https you@example.com"
exit 0
