#!/bin/sh

fail() { echo "$*" >&2; exit 1; }

url_decode() {
    printf '%s\n' "$1" | sed 's/+/ /g' | awk '{
        out=""; n=length($0)
        for (i=1; i<=n; i++) {
            c=substr($0,i,1)
            if (c=="%" && i+2<=n) {
                h=toupper(substr($0,i+1,2))
                d1=index("0123456789ABCDEF",substr(h,1,1))-1
                d2=index("0123456789ABCDEF",substr(h,2,1))-1
                if (d1>=0 && d2>=0) { out=out sprintf("%c",d1*16+d2); i+=2 }
                else out=out c
            } else out=out c
        }
        printf "%s",out
    }'
}

json_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

param() {
    printf '%s\n' "$PARAMS" | tr '&' '\n' | sed -n "s/^$1=//p" | head -1
}

VLESS=${1:-}
[ -n "$VLESS" ] || fail 'empty VLESS URL'
case "$VLESS" in vless://*) ;; *) fail 'URL must start with vless://' ;; esac

REST=${VLESS#vless://}
UUID=${REST%%@*}
[ "$UUID" != "$REST" ] || fail 'missing @ in VLESS URL'
AFTER_AT=${REST#*@}
HOSTPORT=${AFTER_AT%%\?*}
PARAMS_FRAGMENT=${AFTER_AT#*\?}
[ "$PARAMS_FRAGMENT" != "$AFTER_AT" ] || PARAMS_FRAGMENT=""
PARAMS=${PARAMS_FRAGMENT%%#*}

case "$HOSTPORT" in
    \[*\]:*) HOST=${HOSTPORT%%\]*}; HOST=${HOST#\[}; PORT=${HOSTPORT##*:} ;;
    *:*) HOST=${HOSTPORT%:*}; PORT=${HOSTPORT##*:} ;;
    *) HOST=$HOSTPORT; PORT=443 ;;
esac

case "$PORT" in ''|*[!0-9]*) fail 'invalid VLESS port' ;; esac
[ -n "$UUID" ] || fail 'missing VLESS UUID'
[ -n "$HOST" ] || fail 'missing VLESS host'

SNI=$(url_decode "$(param sni)")
FP=$(url_decode "$(param fp)")
PBK=$(url_decode "$(param pbk)")
SID=$(url_decode "$(param sid)")
FLOW=$(url_decode "$(param flow)")
[ -n "$SNI" ] || SNI=$HOST
[ -n "$FP" ] || FP=chrome

HOST=$(json_escape "$HOST")
UUID=$(json_escape "$UUID")
SNI=$(json_escape "$SNI")
FP=$(json_escape "$FP")
PBK=$(json_escape "$PBK")
SID=$(json_escape "$SID")
FLOW=$(json_escape "$FLOW")

FLOW_LINE=""
[ -n "$FLOW" ] && FLOW_LINE="\"flow\": \"$FLOW\","

cat <<EOF
{
  "log": {"level": "warn", "output": "/var/log/sing-box.log"},
  "dns": {
    "servers": [
      {"tag": "remote", "address": "tls://8.8.8.8", "detour": "proxy"},
      {"tag": "local", "address": "77.88.8.8", "detour": "direct"}
    ],
    "rules": [{"rule_set": "geoip-ru", "server": "local"}],
    "final": "remote",
    "independent_cache": true
  },
  "inbounds": [
    {"type": "tproxy", "tag": "tproxy-in", "listen": "::", "listen_port": 7895,
     "tcp_fast_open": true, "udp_fragment": true, "sniff": true},
    {"type": "mixed", "tag": "health-in", "listen": "127.0.0.1", "listen_port": 2080}
  ],
  "outbounds": [
    {"type": "vless", "tag": "proxy", "server": "$HOST", "server_port": $PORT,
     "uuid": "$UUID", $FLOW_LINE
     "tls": {"enabled": true, "server_name": "$SNI",
       "utls": {"enabled": true, "fingerprint": "$FP"},
       "reality": {"enabled": true, "public_key": "$PBK", "short_id": "$SID"}}},
    {"type": "direct", "tag": "direct"},
    {"type": "block", "tag": "block"}
  ],
  "route": {
    "rules": [
      {"protocol": "dns", "outbound": "direct"},
      {"ip_is_private": true, "outbound": "direct"},
      {"rule_set": "geoip-ru", "outbound": "direct"}
    ],
    "rule_set": [{"type": "remote", "tag": "geoip-ru", "format": "binary",
      "url": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-ru.srs",
      "download_detour": "direct"}],
    "final": "proxy",
    "default_domain_resolver": "local",
    "auto_detect_interface": true
  }
}
EOF
