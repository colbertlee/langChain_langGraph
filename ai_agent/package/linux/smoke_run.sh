#!/usr/bin/env bash
# 模拟 run.sh：注入 stub 二进制
set -e
cd "$(dirname "$0")"

# 临时 stub
echo "#!/usr/bin/env bash" > _stub_agent
echo "echo '[stub] ai-agent started'" >> _stub_agent
echo "exit 0" >> _stub_agent
chmod +x _stub_agent

# 临时改 run.sh，把 ./ai-agent 换成 ./\_stub\_agent（避免 sed 转义问题）
tmp="_run_smoke.sh"
sed 's|./ai-agent|./_stub_agent|g' run.sh > "$tmp"
bash "$tmp"
rm -f "$tmp" _stub_agent
