#!/bin/sh
set -eu

PROJECT=24spark
REPOSITORY=${GITHUB_REPOSITORY:-arankarrr/24spark}
REF=${GITHUB_REF:-main}
BASE_URL=${BASE_URL:-https://raw.githubusercontent.com/$REPOSITORY/$REF}
STAGE=/tmp/24spark-install-$$
BACKUP=/root/24spark-backup-$(date +%Y%m%d-%H%M%S)

say() { printf '%s\n' "[24spark] $*"; }
die() { printf '%s\n' "[24spark] ERROR: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die 'run this installer as root'
[ -f /etc/openwrt_release ] || die 'this installer supports OpenWrt only'

mkdir -p "$STAGE"
trap 'rm -rf "$STAGE"' EXIT

fetch() {
    src=$1
    dst=$2
    if command -v curl >/dev/null 2>&1; then
        if curl -fL \
            --connect-timeout 30 \
            --max-time 180 \
            --retry 4 \
            --retry-delay 3 \
            --retry-all-errors \
            "$BASE_URL/$src" -o "$dst"; then
            return 0
        fi
        say "curl failed for $src; trying another downloader"
    fi
    rm -f "$dst"
    if command -v uclient-fetch >/dev/null 2>&1; then
        if uclient-fetch -T 180 -t 4 -O "$dst" "$BASE_URL/$src"; then
            return 0
        fi
    fi
    rm -f "$dst"
    if command -v wget >/dev/null 2>&1; then
        if wget -T 180 -t 4 -O "$dst" "$BASE_URL/$src"; then
            return 0
        fi
    fi
    die "download failed: $src"
}

package_installed() {
    opkg status "$1" 2>/dev/null | grep -q 'Status:.* installed'
}

MISSING=""
for package in sing-box curl ca-bundle kmod-nft-tproxy kmod-nft-socket; do
    package_installed "$package" || MISSING="$MISSING $package"
done
if [ -n "$MISSING" ]; then
    say "installing packages:$MISSING"
    opkg update
    # shellcheck disable=SC2086
    opkg install $MISSING || die 'package installation failed; check that your feeds provide sing-box'
fi

command -v sing-box >/dev/null 2>&1 || die 'sing-box executable is unavailable'
command -v nft >/dev/null 2>&1 || die 'nftables is unavailable'
command -v jsonfilter >/dev/null 2>&1 || die 'jsonfilter is unavailable'

say 'downloading files'
for file in sb3.cgi singbox.html parse_vless.sh parse_subscription.sh sing-box.init \
            tproxy-setup.sh config.default.json luci-app-singbox.json luci-singbox.js; do
    fetch "$file" "$STAGE/$file"
    [ -s "$STAGE/$file" ] || die "empty download: $file"
done

jsonfilter -q -i "$STAGE/config.default.json" -t '$' >/dev/null || die 'invalid default config JSON'
jsonfilter -q -i "$STAGE/luci-app-singbox.json" -t '$' >/dev/null || die 'invalid LuCI menu JSON'
sh -n "$STAGE/sb3.cgi"
sh -n "$STAGE/parse_vless.sh"
sh -n "$STAGE/parse_subscription.sh"
sh -n "$STAGE/sing-box.init"
sh -n "$STAGE/tproxy-setup.sh"

mkdir -p "$BACKUP" /etc/sing-box /www/cgi-bin
backup_file() {
    [ ! -e "$1" ] || {
        mkdir -p "$BACKUP$(dirname "$1")"
        cp -p "$1" "$BACKUP$1"
    }
}

for target in \
    /www/cgi-bin/sb \
    /www/singbox.html \
    /etc/sing-box/parse_vless.sh \
    /etc/sing-box/parse_subscription.sh \
    /etc/sing-box/tproxy-setup.sh \
    /etc/init.d/sing-box \
    /usr/share/luci/menu.d/luci-app-singbox.json \
    /www/luci-static/resources/view/singbox.js; do
    backup_file "$target"
done

put_file() {
    cp "$1" "$2"
    chmod "$3" "$2"
}

put_file "$STAGE/sb3.cgi" /www/cgi-bin/sb 755
put_file "$STAGE/singbox.html" /www/singbox.html 644
put_file "$STAGE/parse_vless.sh" /etc/sing-box/parse_vless.sh 755
put_file "$STAGE/parse_subscription.sh" /etc/sing-box/parse_subscription.sh 755
put_file "$STAGE/tproxy-setup.sh" /etc/sing-box/tproxy-setup.sh 755
put_file "$STAGE/sing-box.init" /etc/init.d/sing-box 755

if [ -d /usr/share/luci/menu.d ] && [ -d /www/luci-static/resources/view ]; then
    put_file "$STAGE/luci-app-singbox.json" /usr/share/luci/menu.d/luci-app-singbox.json 644
    put_file "$STAGE/luci-singbox.js" /www/luci-static/resources/view/singbox.js 644
    rm -f /tmp/luci-indexcache* /tmp/luci-modulecache/*
fi

[ -e /etc/sing-box/subscriptions.txt ] || : > /etc/sing-box/subscriptions.txt
chmod 600 /etc/sing-box/subscriptions.txt

if [ ! -s /etc/sing-box/config.json ]; then
    put_file "$STAGE/config.default.json" /etc/sing-box/config.json 600
fi

if ! sing-box check -c /etc/sing-box/config.json; then
    die "existing config is invalid; backup is in $BACKUP"
fi

/etc/init.d/sing-box enable
if /etc/init.d/sing-box running 2>/dev/null; then
    /etc/init.d/sing-box restart
else
    /etc/init.d/sing-box start
fi

say 'installation complete'
say "backup: $BACKUP"
say 'panel: http://ROUTER_IP/cgi-bin/luci/admin/services/singbox'
say 'if the Services menu was already open, sign out of LuCI and sign in again'
