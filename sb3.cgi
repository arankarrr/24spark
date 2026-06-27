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
MANUAL_FILE=/etc/sing-box/manual_nodes.txt
ROUTES_FILE=/etc/sing-box/custom_direct.txt
CFG=/etc/sing-box/config.json
LOG=/var/log/sing-box.log

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
    for UA in "clash" "v2rayNG/1.8.0" "Happ/1.0"; do
        RAW=$(curl -sL --max-time 15 -H "Accept-Encoding: identity" -A "$UA" "$U" 2>/dev/null)
        DEC=$(printf '%s' "$RAW" | base64 -d 2>/dev/null)
        if echo "$DEC" | grep -q '^vless://'; then echo "$DEC" | grep '^vless://'; return; fi
        if echo "$RAW" | grep -q '^vless://'; then echo "$RAW" | grep '^vless://'; return; fi
        if echo "$RAW" | grep -q '"protocol":"vless"'; then
            echo "$RAW" | awk '
            /"protocol":"vless"/{found=1;host="";port="";uuid="";flow="";fp="";sni="";pbk="";sid=""}
            found && /"address":/{match($0,/"address":"([^"]+)"/,a);host=a[1]}
            found && /"port":/{match($0,/"port":([0-9]+)/,a);port=a[1]}
            found && /"id":/{match($0,/"id":"([^"]+)"/,a);uuid=a[1]}
            found && /"flow":/{match($0,/"flow":"([^"]+)"/,a);flow=a[1]}
            found && /"fingerprint":/{match($0,/"fingerprint":"([^"]+)"/,a);fp=a[1]}
            found && /"serverName":/{match($0,/"serverName":"([^"]+)"/,a);sni=a[1]}
            found && /"publicKey":/{match($0,/"publicKey":"([^"]+)"/,a);pbk=a[1]}
            found && /"shortId":/{match($0,/"shortId":"([^"]+)"/,a);sid=a[1]}
            found && host!=""&&port!=""&&uuid!=""&&uuid!="00000000-0000-0000-0000-000000000000"{
                f=(flow!=""?"&flow="flow:"")
                fp2=(fp!=""?fp:"chrome")
                printf "vless://%s@%s:%s?type=tcp&security=reality&pbk=%s&fp=%s&sni=%s&sid=%s%s#node\n",uuid,host,port,pbk,fp2,sni,sid,f
                found=0
            }'
            return
        fi
    done
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
        awk '{gsub(/"/,"\\\""); printf "%s{\"type\":\"sub\",\"url\":\"%s\"}",(NR>1?",":""),$0}')
    M=$(cat "$MANUAL_FILE" 2>/dev/null | grep '^vless://' | \
        awk '{gsub(/"/,"\\\""); printf "%s{\"type\":\"node\",\"url\":\"%s\"}",(NR>1?",":""),$0}')
    SEP=""
    [ -n "$R" ] && [ -n "$M" ] && SEP=","
    printf '{"subs":[%s%s%s]}\n' "$R" "$SEP" "$M"
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

addnode)
    RAW=$(echo "$QUERY" | sed "s/.*url=//;s/[& ].*//")
    URL=$(url_decode "$RAW")
    [ -z "$URL" ] && printf '{"ok":false,"error":"empty url"}\n' && exit
    case "$URL" in
        vless://*) ;;
        *) printf '{"ok":false,"error":"not a vless:// url"}\n'; exit ;;
    esac
    touch "$MANUAL_FILE"
    if grep -qF "$URL" "$MANUAL_FILE"; then
        printf '{"ok":false,"error":"already exists"}\n'; exit
    fi
    printf '%s\n' "$URL" >> "$MANUAL_FILE"
    printf '{"ok":true}\n'
    ;;

delnode)
    RAW=$(echo "$QUERY" | sed "s/.*url=//;s/[& ].*//")
    URL=$(url_decode "$RAW")
    [ -z "$URL" ] && printf '{"ok":false,"error":"empty url"}\n' && exit
    SAFE=$(printf '%s' "$URL" | sed 's|[\\&]|\\&|g;s|/|\\/|g')
    sed -i "\\|^${SAFE}$|d" "$MANUAL_FILE" 2>/dev/null
    printf '{"ok":true}\n'
    ;;

nodes)
    ALL_FETCH=""
    SUBS=$(cat "$SUBS_FILE" 2>/dev/null | grep -v '^[[:space:]]*$')
    if [ -n "$SUBS" ]; then
        ALL_FETCH=$(echo "$SUBS" | while IFS= read -r U; do
            [ -z "$U" ] && continue
            fetch_vless "$U"
        done | grep '^vless://' | grep -v '@0\.0\.0\.0:')
    fi
    MANUAL=$(cat "$MANUAL_FILE" 2>/dev/null | grep '^vless://' | grep -v '@0\.0\.0\.0:')
    ALL=$(printf '%s\n%s' "$ALL_FETCH" "$MANUAL" | grep '^vless://')
    [ -z "$ALL" ] && printf '{"nodes":[]}\n' && exit
    JSON=$(printf '%s\n' "$ALL" | awk 'BEGIN{printf "[";i=0}{i++;line=$0;if(i>1)printf ",";n=split(line,a,"#");lbl=(n>1)?a[n]:"Node"i;gsub(/"/,"",lbl);h=line;sub(/vless:\/\/[^@]*@/,"",h);split(h,hp,":");host=hp[1];p=h;sub(/[^:]*:/,"",p);split(p,pp,"?");port=pp[1];raw=line;gsub(/"/,"\\\"",raw);printf "{\"idx\":%d,\"label\":\"%s\",\"host\":\"%s\",\"port\":\"%s\",\"raw\":\"%s\"}",i,lbl,host,port,raw}END{printf "]"}')
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
    printf '{"ok":true,"pid":"%s"}\n' "${PID:-}"
    ;;

listroutes)
    R=$(cat "$ROUTES_FILE" 2>/dev/null | grep -v '^[[:space:]]*$' | awk -F'|' '{
        lbl=$1; cidr=$2
        gsub(/"/,"\\\"",lbl); gsub(/"/,"\\\"",cidr)
        printf "%s{\"label\":\"%s\",\"cidr\":\"%s\"}",(NR>1?",":""),lbl,cidr
    }')
    printf '{"routes":[%s]}\n' "$R"
    ;;

addroute)
    RAWL=$(echo "$QUERY" | sed "s/.*label=//;s/[&].*//")
    RAWC=$(echo "$QUERY" | sed "s/.*cidr=//;s/[& ].*//")
    LBL=$(url_decode "$RAWL")
    CIDR=$(url_decode "$RAWC")
    [ -z "$LBL" ] || [ -z "$CIDR" ] && printf '{"ok":false,"error":"empty label or cidr"}\n' && exit
    touch "$ROUTES_FILE"
    if grep -qF "$CIDR" "$ROUTES_FILE"; then
        printf '{"ok":false,"error":"already exists"}\n'; exit
    fi
    printf '%s|%s\n' "$LBL" "$CIDR" >> "$ROUTES_FILE"
    nft add element inet sing_box custom_direct "{ $CIDR }" 2>/dev/null || true
    printf '{"ok":true}\n'
    ;;

delroute)
    RAWC=$(echo "$QUERY" | sed "s/.*cidr=//;s/[& ].*//")
    CIDR=$(url_decode "$RAWC")
    [ -z "$CIDR" ] && printf '{"ok":false,"error":"empty cidr"}\n' && exit
    SAFE=$(printf '%s' "$CIDR" | sed 's|[\\&/]|\\&|g')
    sed -i "/|${SAFE}$/d" "$ROUTES_FILE" 2>/dev/null
    nft delete element inet sing_box custom_direct "{ $CIDR }" 2>/dev/null || true
    printf '{"ok":true}\n'
    ;;

*)  printf '{"error":"unknown: %s"}\n' "$ACTION" ;;
esac
