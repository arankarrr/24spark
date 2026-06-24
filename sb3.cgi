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

case "$ACTION" in
status)
    PID=$(ps 2>/dev/null | grep "sing-box" | grep -v grep | awk '{print $1}' | head -1)
    [ -n "$PID" ] && R=true || R=false
    printf '{"running":%s,"pid":"%s"}\n' "$R" "${PID:-}"
    ;;

log)
    L=$(tail -60 "$LOG" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g;s/\\/\\\\/g;s/"/\\"/g' | awk '{printf "%s|",$0}')
    printf '{"log":"%s"}\n' "$L"
    ;;

start)
    /etc/init.d/sing-box start 2>/dev/null; sleep 1
    PID=$(ps 2>/dev/null | grep "sing-box" | grep -v grep | awk '{print $1}' | head -1)
    printf '{"ok":true,"pid":"%s"}\n' "${PID:-}"
    ;;

stop)
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
    SUBS=$(cat "$SUBS_FILE" 2>/dev/null | grep -v '^[[:space:]]*$')
    [ -z "$SUBS" ] && printf '{"nodes":[]}\n' && exit
    ALL=$(echo "$SUBS" | while IFS= read -r U; do
        [ -z "$U" ] && continue
        fetch_vless "$U"
    done | grep '^vless://' | grep -v '@0\.0\.0\.0:')
    [ -z "$ALL" ] && printf '{"nodes":[]}\n' && exit
    if [ ! -s "$ACTIVE_FILE" ]; then
        CFG_HOST=$(jsonfilter -q -i "$CFG" -e '$.outbounds[0].server' 2>/dev/null)
        CFG_PORT=$(jsonfilter -q -i "$CFG" -e '$.outbounds[0].server_port' 2>/dev/null)
        CFG_UUID=$(jsonfilter -q -i "$CFG" -e '$.outbounds[0].uuid' 2>/dev/null)
        if [ -n "$CFG_HOST" ] && [ -n "$CFG_PORT" ] && [ -n "$CFG_UUID" ]; then
            DETECTED=$(printf '%s\n' "$ALL" | grep -F "vless://$CFG_UUID@$CFG_HOST:$CFG_PORT?" | head -1)
            if [ -n "$DETECTED" ]; then
                umask 077
                printf '%s\n' "$DETECTED" > "$ACTIVE_FILE"
            fi
        fi
    fi
    ACTIVE=$(cat "$ACTIVE_FILE" 2>/dev/null | tr -d '\r\n')
    JSON=$(printf '%s\n' "$ALL" | awk -v active="$ACTIVE" 'BEGIN{printf "[";i=0}{i++;line=$0;is_active=(line==active?"true":"false");if(i>1)printf ",";n=split(line,a,"#");lbl=(n>1)?a[n]:"Node"i;gsub(/"/,"",lbl);h=line;sub(/vless:\/\/[^@]*@/,"",h);split(h,hp,":");host=hp[1];p=h;sub(/[^:]*:/,"",p);split(p,pp,"?");port=pp[1];raw=line;gsub(/"/,"\\\"",raw);printf "{\"idx\":%d,\"label\":\"%s\",\"host\":\"%s\",\"port\":\"%s\",\"raw\":\"%s\",\"active\":%s}",i,lbl,host,port,raw,is_active}END{printf "]"}')
    printf '{"nodes":%s}\n' "$JSON"
    ;;

setnode)
    RAW=$(echo "$QUERY" | sed "s/.*raw=//")
    [ -z "$RAW" ] && printf '{"ok":false,"error":"empty raw"}\n' && exit
    VLESS=$(url_decode "$RAW")
    [ -z "$VLESS" ] && printf '{"ok":false,"error":"empty vless"}\n' && exit
    /etc/sing-box/parse_vless.sh "$VLESS" > "$CFG" 2>/tmp/pvls_err
    if [ $? -ne 0 ]; then
        ERR=$(sed 's/"/\\"/g' /tmp/pvls_err 2>/dev/null | head -1)
        printf '{"ok":false,"error":"%s"}\n' "$ERR"; exit
    fi
    /etc/init.d/sing-box restart 2>/dev/null; sleep 2
    PID=$(ps 2>/dev/null | grep "sing-box" | grep -v grep | awk '{print $1}' | head -1)
    if [ -n "$PID" ]; then
        umask 077
        printf '%s\n' "$VLESS" > "$ACTIVE_FILE"
    fi
    printf '{"ok":true,"pid":"%s"}\n' "${PID:-}"
    ;;

*)  printf '{"error":"unknown: %s"}\n' "$ACTION" ;;
esac
