#!/usr/bin/env bash
# 模拟 install.sh 流程：创建 .env、logs uploads data
set -e
cd "$(dirname "$0")"

# 注入 stub
[ -f .env ] && rm -f .env
for d in logs uploads data; do [ -d "$d" ] && rm -rf "$d"; done

# 临时拷一份 install.sh，把 chmod +x 注释掉
tmp="_install_smoke.sh"
sed 's/^chmod +x/# chmod +x/' install.sh > "$tmp"
bash "$tmp"
rm -f "$tmp"

echo "----- check -----"
[ -f .env ]   && echo "OK .env created" || echo "FAIL .env missing"
for d in logs uploads data; do
  [ -d "$d" ] && echo "OK $d/" || echo "FAIL $d missing"
done
