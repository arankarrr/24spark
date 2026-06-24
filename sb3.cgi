#!/bin/sh
echo "Content-Type: application/json"
echo "Access-Control-Allow-Origin: *"
echo ""

if [ -n "$QUERY_STRING" ]; then
    QUERY="$QUERY_STRING"
elif [ -n "$CONTENT_LENGTH" ] && [ "$CONTENT_LENGTH" -gt 0 ] 2>/dev/null; then
    QUERY=$(head -c "$CONTENT_LENGTH")
else
    QUERY=$(cat)
fi
ACTION=$(echo "$QUERY" | sed "s/.*action=//;s/[&#].*//")

SUBS_FILE=/etc/sing-box/subscriptions.txt
CFG=/etc/sing-box/config.json
LOG=/var/log/sing-box.log
HWID_FILE=/etc/sing-box/happ.hwid
ACTIVE_FILE=/etc/sing-box/active_node.url
NODES_FILE=/etc/sing-box/nodes.cache
LATENCY_FILE=/tmp/24spark-latency.tsv
HEALTH_FILE=/tmp/24spark-health
MANAGER=/etc/sing-box/24spark-manager.sh

url_decode() {
    printf '%s\n' "$1" | sed 's/+/ /g' | awk '{
        out=""
        n=length($0)
        for(i=1;i<=n;i++){
            c=substr($0,i,1)
            if(c=="%"&&i+2<=n){
                h=toupper(substr($0,i+1,2))
                d1=index("0123456789ABCDEF",substr(h,1,1))-1
                d2=index("0123456789ABCDEF",substr(h,2,1))-1
                if(d1>=0&&d2>=0){out=out sprintf("%c",d1*16+d2);i+=2}
                else out=out c
            } else out=out c
        }
        printf "%s",out
    }'
}

fetch_vless() {
    U="$1"
    for UA in "clash" "v2rayNG/1.8.0"; do
        RAW=$(curl -sL --max-time 15 -H "Accept-Encoding: identity" -A "$UA" "$U" 2>/dev/null)
        DEC=$(printf '%s' "$RAW" | base64 -d 2>/dev/null)
        NODES=$(printf '%s\n' "$DEC" | grep '^vless://' | grep -v '@0\.0\.0\.0:')
        if [ -n "$NODES" ]; then
            printf '%s\n' "$NODES"
            return
        fi
        NODES=$(printf '%s\n' "$RAW" | grep '^vless://' | grep -v '@0\.0\.0\.0:')
        if [ -n "$NODES" ]; then
            printf '%s\n' "$NODES"
            return
        fi
    done

    if [ ! -s "$HWID_FILE" ]; then
        umask 077
        SEED=$(cat /etc/machine-id 2>/dev/null)
        [ -n "$SEED" ] || SEED="$(hostname)-$(cat /sys/class/net/br-lan/address 2>/dev/null)"
        printf '%s' "$SEED" | sha256sum | awk '{print $1}' > "$HWID_FILE"
    fi
    HWID=$(cat "$HWID_FILE" 2>/dev/null)
    RELEASE=$(sed -n "s/^DISTRIB_RELEASE='\(.*\)'/\1/p" /etc/openwrt_release 2>/dev/null)
    [ -n "$RELEASE" ] || RELEASE=unknown
    RAW=$(curl -sL --max-time 20 -H "Accept-Encoding: identity" \
        -H "X-Hwid: $HWID" \
        -H "X-Device-OS: OpenWrt" \
        -H "X-Ver-OS: $RELEASE" \
        -H "X-Device-Model: OpenWrt Router" \
        -H "X-Device-Name: 24spark" \
        -H "X-App-Version: 3.0.0" \
        -H "X-App-Name: Happ" \
        -A "Happ/3.0.0" "$U" 2>/dev/null)
    printf '%s' "$RAW" | /etc/sing-box/parse_subscription.sh 2>/dev/null
}

health_value() {
    sed -n "s/^$1=//p" "$HEALTH_FILE" 2>/dev/null | head -1
}

render_nodes() {
    ACTIVE=$(cat "$ACTIVE_FILE" 2>/dev/null | tr -d '\r\n')
    [ -s "$LATENCY_FILE" ] || { printf '{"nodes":[]}\n'; return; }
    JSON=$(awk -F '\t' -v active="$ACTIVE" 'BEGIN{printf "[";i=0}
      NF>=2 {ms=$1; line=$0; sub(/^[^\t]*\t/,"",line); i++; is_active=(line==active?"true":"false");
        n=split(line,a,"#"); lbl=(n>1)?a[n]:"Node"i; gsub(/"/,"",lbl);
        h=line; sub(/vless:\/\/[^@]*@/,"",h); split(h,hp,":"); host=hp[1];
        p=h; sub(/[^:]*:/,"",p); split(p,pp,"?"); port=pp[1]; raw=line;
        gsub(/\\/,"\\\\",raw); gsub(/"/,"\\\"",raw);
        if(i>1)printf ",";
        printf "{\"idx\":%d,\"label\":\"%s\",\"country\":\"%s\",\"host\":\"%s\",\"port\":\"%s\",\"raw\":\"%s\",\"latency\":%s,\"active\":%s}",i,lbl,lbl,host,port,raw,(ms<999999?ms:"null"),is_active
      } END{printf "]"}' "$LATENCY_FILE")
    printf '{"nodes":%s}\n' "$JSON"
}

case "$ACTION" in
status)
    PID=$(ps 2>/dev/null | grep "sing-box" | grep -v grep | awk '{print $1}' | head -1)
    [ -n "$PID" ] && R=true || R=false
    INTERNET=$(health_value internet); DNS=$(health_value dns); TPROXY=$(health_value tproxy)
    [ "$INTERNET" = 1 ] && INTERNET=true || INTERNET=false
    [ "$DNS" = 1 ] && DNS=true || DNS=false
    [ "$TPROXY" = 1 ] && TPROXY=true || TPROXY=false
    LATENCY=$(health_value active_latency); [ "${LATENCY:-999999}" -lt 999999 ] 2>/dev/null || LATENCY=null
    LAST_REFRESH=$(health_value last_refresh); LAST_CHECK=$(health_value last_check)
    printf '{"running":%s,"pid":"%s","internet":%s,"dns":%s,"tproxy":%s,"latency":%s,"last_refresh":%s,"last_check":%s}\n' \
        "$R" "${PID:-}" "$INTERNET" "$DNS" "$TPROXY" "$LATENCY" "${LAST_REFRESH:-0}" "${LAST_CHECK:-0}"
    ;;

log)
    L=$(tail -60 "$LOG" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g;s/\\/\\\\/g;s/"/\\"/g' | awk '{printf "%s|",$0}')
    printf '{"log":"%s"}\n' "$L"
    ;;

start)
    rm -f /tmp/24spark-paused
    /etc/init.d/sing-box start 2>/dev/null; sleep 1
    PID=$(ps 2>/dev/null | grep "sing-box" | grep -v grep | awk '{print $1}' | head -1)
    printf '{"ok":true,"pid":"%s"}\n' "${PID:-}"
    ;;

stop)
    touch /tmp/24spark-paused
    /etc/init.d/sing-box stop 2>/dev/null
    printf '{"ok":true}\n'
    ;;

listsubs)
    R=$(cat "$SUBS_FILE" 2>/dev/null | grep -v '^[[:space:]]*$' | \
        awk '{gsub(/"/,"\\\""); printf "%s{\"url\":\"%s\"}",(NR>1?",":""),$0}')
    printf '{"subs":[%s]}\n' "$R"
    ;;

addsub)
    RAW=$(echo "$QUERY" | sed "s/.*url=//;s/[& ].*//")
    URL=$(url_decode "$RAW")
    [ -z "$URL" ] && printf '{"ok":false,"error":"empty url"}\n' && exit
    touch "$SUBS_FILE"
    if grep -qF "$URL" "$SUBS_FILE"; then
        printf '{"ok":false,"error":"already exists"}\n'; exit
    fi
    printf '%s\n' "$URL" >> "$SUBS_FILE"
    printf '{"ok":true}\n'
    ;;

delsub)
    RAW=$(echo "$QUERY" | sed "s/.*url=//;s/[& ].*//")
    URL=$(url_decode "$RAW")
    [ -z "$URL" ] && printf '{"ok":false,"error":"empty url"}\n' && exit
    SAFE=$(printf '%s' "$URL" | sed 's|[\\&]|\\&|g;s|/|\\/|g')
    sed -i "\\|^${SAFE}$|d" "$SUBS_FILE" 2>/dev/null
    printf '{"ok":true}\n'
    ;;

nodes)
    [ -s "$NODES_FILE" ] || "$MANAGER" refresh >/dev/null 2>&1
    [ -s "$LATENCY_FILE" ] || "$MANAGER" benchmark >/dev/null 2>&1
    render_nodes
    ;;

refreshnodes)
    if "$MANAGER" refresh >/dev/null 2>&1; then
        "$MANAGER" benchmark >/dev/null 2>&1
        render_nodes
    else
        printf '{"nodes":[],"error":"subscription refresh failed"}\n'
    fi
    ;;

setnode)
    RAW=$(echo "$QUERY" | sed "s/.*raw=//")
    [ -z "$RAW" ] && printf '{"ok":false,"error":"empty raw"}\n' && exit
    VLESS=$(url_decode "$RAW")
    [ -z "$VLESS" ] && printf '{"ok":false,"error":"empty vless"}\n' && exit
    rm -f /tmp/24spark-paused
    "$MANAGER" apply "$VLESS"
    RC=$?
    PID=$(ps 2>/dev/null | grep "sing-box" | grep -v grep | awk '{print $1}' | head -1)
    if [ "$RC" = 0 ] && [ -n "$PID" ]; then
        printf '{"ok":true,"pid":"%s"}\n' "$PID"
    else
        ERR=$(tail -1 /tmp/24spark-config-error 2>/dev/null | sed 's/"/\\"/g')
        [ -n "$ERR" ] || ERR=$(logread 2>/dev/null | grep -i 'sing-box' | tail -1 | sed 's/"/\\"/g')
        printf '{"ok":false,"error":"%s"}\n' "${ERR:-sing-box failed to start}"
    fi
    ;;

update)
    if [ "$(cat /tmp/24spark-update.state 2>/dev/null)" = running ]; then
        printf '{"ok":false,"error":"update already running"}\n'; exit
    fi
    echo running > /tmp/24spark-update.state
    (
        if curl -fL --connect-timeout 30 --max-time 300 \
            -o /tmp/24spark-install.sh \
            https://raw.githubusercontent.com/arankarrr/24spark/main/install.sh && \
           sh /tmp/24spark-install.sh; then
            echo success > /tmp/24spark-update.state
        else
            echo error > /tmp/24spark-update.state
        fi
    ) >/tmp/24spark-update.log 2>&1 </dev/null &
    printf '{"ok":true}\n'
    ;;

updatestatus)
    STATE=$(cat /tmp/24spark-update.state 2>/dev/null); [ -n "$STATE" ] || STATE=idle
    printf '{"state":"%s"}\n' "$STATE"
    ;;

*)  printf '{"error":"unknown: %s"}\n' "$ACTION" ;;
esac
