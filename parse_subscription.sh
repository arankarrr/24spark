#!/bin/sh

JSON="/tmp/singbox-sub-$$.json"
SEEN="/tmp/singbox-seen-$$"
trap 'rm -f "$JSON" "$SEEN"' EXIT
cat > "$JSON"
: > "$SEEN"

jget() {
    jsonfilter -q -i "$JSON" -e "$1" 2>/dev/null | head -1
}

urlencode() {
    printf '%s' "$1" | hexdump -v -e '1/1 "%02x"' | sed 's/../%&/g'
}

COUNT=$(jsonfilter -q -i "$JSON" -e '$[*].remarks' 2>/dev/null | wc -l)
[ "$COUNT" -gt 0 ] 2>/dev/null || exit 0

# Process the specific country profiles before the aggregate "fastest" profile.
# This preserves useful labels while the seen-file removes duplicate servers.
CI=$((COUNT - 1))
while [ "$CI" -ge 0 ]; do
    LABEL=$(jget "\$[$CI].remarks")
    OI=0
    while :; do
        PROTO=$(jget "\$[$CI].outbounds[$OI].protocol")
        [ -n "$PROTO" ] || break
        if [ "$PROTO" = "vless" ]; then
            BASE="\$[$CI].outbounds[$OI]"
            HOST=$(jget "$BASE.settings.vnext[0].address")
            PORT=$(jget "$BASE.settings.vnext[0].port")
            UUID=$(jget "$BASE.settings.vnext[0].users[0].id")
            FLOW=$(jget "$BASE.settings.vnext[0].users[0].flow")
            NETWORK=$(jget "$BASE.streamSettings.network")
            SECURITY=$(jget "$BASE.streamSettings.security")
            SNI=$(jget "$BASE.streamSettings.realitySettings.serverName")
            PBK=$(jget "$BASE.streamSettings.realitySettings.publicKey")
            SID=$(jget "$BASE.streamSettings.realitySettings.shortId")
            FP=$(jget "$BASE.streamSettings.realitySettings.fingerprint")
            [ -n "$NETWORK" ] || NETWORK=tcp
            [ -n "$SECURITY" ] || SECURITY=reality
            [ -n "$SNI" ] || SNI="$HOST"
            [ -n "$FP" ] || FP=chrome
            KEY="$UUID@$HOST:$PORT"
            if [ -n "$UUID" ] && [ -n "$HOST" ] && [ "$HOST" != "0.0.0.0" ] && \
               [ -n "$PORT" ] && ! grep -qxF "$KEY" "$SEEN"; then
                printf '%s\n' "$KEY" >> "$SEEN"
                FLOW_Q=""
                [ -n "$FLOW" ] && FLOW_Q="&flow=$FLOW"
                printf 'vless://%s@%s:%s?type=%s&security=%s&pbk=%s&fp=%s&sni=%s&sid=%s%s#%s\n' \
                    "$UUID" "$HOST" "$PORT" "$NETWORK" "$SECURITY" "$PBK" "$FP" \
                    "$SNI" "$SID" "$FLOW_Q" "$(urlencode "${LABEL:-VLESS}")"
            fi
        fi
        OI=$((OI + 1))
    done
    CI=$((CI - 1))
done
