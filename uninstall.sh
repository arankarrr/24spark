#!/bin/sh
set -eu

[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }

/etc/init.d/24spark stop 2>/dev/null || true
/etc/init.d/24spark disable 2>/dev/null || true
/etc/init.d/sing-box stop 2>/dev/null || true
/etc/init.d/sing-box disable 2>/dev/null || true

rm -f \
    /www/cgi-bin/sb \
    /www/singbox.html \
    /etc/sing-box/parse_vless.sh \
    /etc/sing-box/parse_subscription.sh \
    /etc/sing-box/24spark-manager.sh \
    /etc/sing-box/tproxy-setup.sh \
    /etc/init.d/24spark \
    /etc/init.d/sing-box \
    /usr/share/luci/menu.d/luci-app-singbox.json \
    /www/luci-static/resources/view/singbox.js

rm -f /tmp/luci-indexcache* /tmp/luci-modulecache/*

if [ "${1:-}" = '--purge' ]; then
    rm -f /etc/sing-box/config.json /etc/sing-box/subscriptions.txt \
        /etc/sing-box/happ.hwid /etc/sing-box/active_node.url \
        /etc/sing-box/nodes.cache
fi

echo '24spark integration removed. The sing-box package and configuration were preserved.'
