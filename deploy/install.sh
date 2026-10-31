#!/bin/bash
# One-shot installer for the rung sheet on a RHEL 8/9 EC2 instance.
#
#   unzip dad-trader.zip && cd dad-trader && bash deploy/install.sh [--https you@example.com]
#
# What it does:
#   1. installs Python 3.11 and tools          5. password-protects the site (asks you for passwords)
#   2. copies the app to /opt/dad-trader       6. schedules refreshes at 8:30, 12:00, 3:15 CT on weekdays
#   3. builds the database from the sheets     7. (with --https) gets a Let's Encrypt certificate
#   4. publishes the rung sheet to the site
# Safe to re-run: it updates the code and keeps the existing database settings and passwords.
set -euo pipefail

APP=/opt/dad-trader
DOMAIN=trader.wellslabs.dev
HTTPS_EMAIL=""
[[ "${1:-}" == "--https" ]] && HTTPS_EMAIL="${2:?give an email after --https}"
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
tar -C "$SRC" --exclude=./.venv --exclude='./data/*.db' --exclude=./out --exclude=./.git -cf - . | sudo tar -C "$APP" -xf -
sudo chown -R "$USER": "$APP"
cd "$APP"
python3.11 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt yfinance

say "Running tests"
python -m pytest -q

say "Building the database from the sheets"
python -m trader seed

say "Writing the publish script"
cat > "$APP/publish.sh" <<EOF
#!/bin/bash
# Refresh prices, rebuild the rung sheet, and put it on the site.
set -uo pipefail
cd $APP
source .venv/bin/activate
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
  else
    echo "WARN: couldn't find where to add the password lines. Add these two lines inside your server { } block:"
    echo '  auth_basic "Rung Sheet";'; echo '  auth_basic_user_file /etc/trader.htpasswd;'
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
[[ -z "$HTTPS_EMAIL" ]] && echo "Not on HTTPS yet — passwords travel unencrypted. Re-run with: bash deploy/install.sh --https you@example.com"
exit 0
