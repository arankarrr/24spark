#!/bin/sh

ip rule del fwmark 1 table 100 2>/dev/null || true
ip rule add fwmark 1 table 100
ip route flush table 100 2>/dev/null || true
ip route add local default dev lo table 100

ip rule del fwmark 255 table main 2>/dev/null || true
ip rule add fwmark 255 table main priority 10

nft add table inet sing_box 2>/dev/null || true
nft flush table inet sing_box
nft add chain inet sing_box prerouting '{ type filter hook prerouting priority mangle; policy accept; }'
nft add rule inet sing_box prerouting meta l4proto '{ tcp, udp }' fib daddr type local accept
nft add rule inet sing_box prerouting mark 0x1 accept
nft add rule inet sing_box prerouting ip daddr '{ 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8 }' accept
nft add rule inet sing_box prerouting meta l4proto tcp tproxy to :7895 meta mark set 0x1
nft add rule inet sing_box prerouting meta l4proto udp tproxy to :7895 meta mark set 0x1
