#!/bin/sh
export ENABLE_DEPRECATED_SPECIAL_OUTBOUNDS=true

BASE=/etc/sing-box
SUBS=$BASE/subscriptions.txt
CUSTOM=$BASE/custom_nodes.txt
NODES=$BASE/nodes.cache
LATENCY=/tmp/24spark-latency.tsv
HEALTH=/tmp/24spark-health
ACTIVE=$BASE/active_node.url
CFG=$BASE/config.json
HWID=$BASE/happ.hwid

fetch_subscription() {
    url=$1
    for ua in "clash" "v2rayNG/1.8.0"; do
        raw=$(curl -sL --connect-timeout 10 --max-time 30 -H "Accept-Encoding: identity" -A "$ua" "$url" 2>/dev/null)
        decoded=$(printf '%s' "$raw" | base64 -d 2>/dev/null)
        nodes=$(printf '%s\n' "$decoded" | grep '^vless://' | grep -v '@0\.0\.0\.0:')
        [ -n "$nodes" ] || nodes=$(printf '%s\n' "$raw" | grep '^vless://' | grep -v '@0\.0\.0\.0:')
        if [ -n "$nodes" ]; then
            printf '%s\n' "$nodes"
            return 0
        fi
    done

    if [ ! -s "$HWID" ]; then
        umask 077
        seed=$(cat /etc/machine-id 2>/dev/null)
        [ -n "$seed" ] || seed="$(hostname)-$(cat /sys/class/net/br-lan/address 2>/dev/null)"
        printf '%s' "$seed" | sha256sum | awk '{print $1}' > "$HWID"
    fi
    release=$(sed -n "s/^DISTRIB_RELEASE='\(.*\)'/\1/p" /etc/openwrt_release 2>/dev/null)
    [ -n "$release" ] || release=unknown
    curl -sL --connect-timeout 10 --max-time 40 -H "Accept-Encoding: identity" \
        -H "X-Hwid: $(cat "$HWID")" -H "X-Device-OS: OpenWrt" \
        -H "X-Ver-OS: $release" -H "X-Device-Model: OpenWrt Router" \
        -H "X-Device-Name: 24spark" -H "X-App-Version: 3.0.0" \
        -H "X-App-Name: Happ" -A "Happ/3.0.0" "$url" 2>/dev/null | \
        "$BASE/parse_subscription.sh" 2>/dev/null
}

refresh_nodes() {
    lock=/tmp/24spark-refresh.lock
    mkdir "$lock" 2>/dev/null || return 2
    tmp=$NODES.new.$$
    : > "$tmp"
    [ -s "$CUSTOM" ] && grep '^vless://' "$CUSTOM" >> "$tmp"
    while IFS= read -r url; do
        [ -n "$url" ] && fetch_subscription "$url" >> "$tmp"
    done < "$SUBS"
    if grep -q '^vless://' "$tmp"; then
        sort -u "$tmp" > "$NODES"
        chmod 600 "$NODES"
        date +%s > /tmp/24spark-last-refresh
        rc=0
    else
        rc=1
    fi
    rm -f "$tmp"
    rmdir "$lock"
    return "$rc"
}

node_host_port() {
    value=${1#vless://}
    value=${value#*@}
    value=${value%%\?*}
    case "$value" in
        \[*\]:*) host=${value%%\]*}; host=${host#\[}; port=${value##*:} ;;
        *:*) host=${value%:*}; port=${value##*:} ;;
        *) host=$value; port=443 ;;
    esac
}

probe_node() {
    node_host_port "$1"
    case "$port" in ''|*[!0-9]*) echo 999999; return ;; esac
    target=$host
    case "$host" in *:*) target="[$host]" ;; esac
    elapsed=$(curl -k -s -o /dev/null --connect-timeout 3 --max-time 4 \
        -w '%{time_connect}' "https://$target:$port/" 2>/dev/null)
    awk -v t="${elapsed:-0}" 'BEGIN { ms=int(t*1000); print (ms>0 ? ms : 999999) }'
}

benchmark_nodes() {
    [ -s "$NODES" ] || refresh_nodes || return 1
    lock=/tmp/24spark-benchmark.lock
    mkdir "$lock" 2>/dev/null || return 2
    tmp=$LATENCY.new.$$
    : > "$tmp"
    while IFS= read -r node; do
        [ -n "$node" ] || continue
        printf '%s\t%s\n' "$(probe_node "$node")" "$node" >> "$tmp"
    done < "$NODES"
    sort -n "$tmp" > "$LATENCY"
    rm -f "$tmp"
    rmdir "$lock"
}

apply_node() {
    node=$1
    [ -n "$node" ] || return 1
    lock=/tmp/24spark-apply.lock
    mkdir "$lock" 2>/dev/null || return 2
    tmp=$CFG.new.$$
    old=$CFG.old.$$
    cp "$CFG" "$old" 2>/dev/null || true
    if "$BASE/parse_vless.sh" "$node" > "$tmp" 2>/tmp/24spark-config-error && \
       sing-box check -c "$tmp" >>/tmp/24spark-config-error 2>&1; then
        chmod 600 "$tmp"
        mv "$tmp" "$CFG"
        /etc/init.d/sing-box restart >/dev/null 2>&1
        sleep 2
        if /etc/init.d/sing-box running >/dev/null 2>&1; then
            umask 077
            printf '%s\n' "$node" > "$ACTIVE"
            rm -f "$old"
            rc=0
        else
            [ -s "$old" ] && mv "$old" "$CFG"
            /etc/init.d/sing-box restart >/dev/null 2>&1
            rc=1
        fi
    else
        rm -f "$tmp" "$old"
        rc=1
    fi
    rmdir "$lock"
    return "$rc"
}

check_internet() {
    # First test the complete path through sing-box. The IP fallback avoids
    # treating a remote DNS outage as a total proxy outage.
    curl -fsS --proxy socks5h://127.0.0.1:2080 --connect-timeout 4 \
        --max-time 8 -o /dev/null https://www.gstatic.com/generate_204 >/dev/null 2>&1 || \
    curl -kfsS --proxy socks5://127.0.0.1:2080 --connect-timeout 4 \
        --max-time 8 -o /dev/null https://1.1.1.1/cdn-cgi/trace >/dev/null 2>&1
}

check_dns() {
    nslookup openwrt.org 127.0.0.1 >/dev/null 2>&1
}

check_tproxy() {
    nft list table inet sing_box >/dev/null 2>&1 || return 1
    # 7895 = 0x1ED7. /proc is available even when netstat/ss applets are not.
    awk '$2 ~ /:1ED7$/ && $4 == "0A" { found=1 } END { exit !found }' \
        /proc/net/tcp /proc/net/tcp6 2>/dev/null
}

write_health() {
    tmp=$HEALTH.new.$$
    {
        echo "internet=$internet"
        echo "dns=$dns"
        echo "singbox=$singbox"
        echo "tproxy=$tproxy"
        echo "failures=$failures"
        echo "active_latency=$active_latency"
        echo "last_check=$(date +%s)"
        echo "last_refresh=$(cat /tmp/24spark-last-refresh 2>/dev/null)"
        echo "last_switch=$last_switch"
        echo "reason=$reason"
    } > "$tmp"
    mv "$tmp" "$HEALTH"
}

daemon_loop() {
    failures=0
    last_switch=0
    reason=startup
    refresh_nodes
    benchmark_nodes
    last_refresh=$(date +%s)
    while :; do
        now=$(date +%s)
        if [ $((now - last_refresh)) -ge 3600 ]; then
            if refresh_nodes; then
                benchmark_nodes
                reason=subscription_refreshed
            else
                reason=subscription_refresh_failed
            fi
            last_refresh=$now
        fi

        if [ -e /tmp/24spark-paused ]; then
            /etc/init.d/sing-box running >/dev/null 2>&1 && singbox=1 || singbox=0
            internet=0
            check_dns && dns=1 || dns=0
            check_tproxy && tproxy=1 || tproxy=0
            active_latency=999999
            reason=paused
            write_health
            sleep 30
            continue
        fi

        /etc/init.d/sing-box running >/dev/null 2>&1 || /etc/init.d/sing-box start >/dev/null 2>&1
        /etc/init.d/sing-box running >/dev/null 2>&1 && singbox=1 || singbox=0
        check_internet && internet=1 || internet=0
        check_dns && dns=1 || dns=0
        check_tproxy && tproxy=1 || tproxy=0
        if [ -s "$ACTIVE" ]; then active=$(tr -d '\r\n' < "$ACTIVE"); else active=; fi
        if [ -n "$active" ]; then active_latency=$(probe_node "$active"); else active_latency=999999; fi
        if [ "$singbox" = 1 ] && [ "$internet" = 1 ] && [ "$active_latency" -lt 999999 ]; then
            failures=0
        else
            failures=$((failures + 1))
            reason=connection_check_failed
        fi

        if [ "$failures" -ge 3 ]; then
            benchmark_nodes
            best_ms=$(awk 'NR==1{print $1}' "$LATENCY" 2>/dev/null)
            best=$(awk 'NR==1{sub(/^[^\t]*\t/,"");print}' "$LATENCY" 2>/dev/null)
            if [ -n "$best" ] && [ "${best_ms:-999999}" -lt 999999 ]; then
                if apply_node "$best"; then
                    active_latency=$best_ms
                    failures=0
                    last_switch=$(date +%s)
                    reason=switched_to_fastest
                else
                    reason=failover_failed
                fi
            fi
        fi
        write_health
        sleep 30
    done
}

case "${1:-}" in
    refresh) refresh_nodes ;;
    benchmark) benchmark_nodes ;;
    probe) probe_node "$2" ;;
    apply) apply_node "$2" ;;
    daemon) daemon_loop ;;
    *) echo 'usage: 24spark-manager.sh refresh|benchmark|probe URL|apply URL|daemon' >&2; exit 2 ;;
esac
