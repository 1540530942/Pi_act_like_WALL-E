# 2026-05-24 树莓派连接问题与自适应连接方案

## 背景

在进行 `audio_recognition`、`action_move`、`front_distance`、实车验证相关工作时，多次需要连接树莓派。最初使用过：

```bash
ssh raspberrypi
```

以及旧文档里的局域网地址：

```text
192.168.137.2
```

后来确认当前树莓派实际局域网 IP 为：

```text
192.168.1.46
```

但连接过程中出现了多种不稳定情况，因此需要记录问题和可用 fallback。

## 问题 1：旧地址不可达

### 现象

旧地址：

```text
192.168.137.2
```

检查结果：

```text
ping 192.168.137.2 -> 100% packet loss
ssh pi@192.168.137.2 -> timed out
http://192.168.137.2:8765/health -> timed out
http://192.168.137.2:18765/health -> timed out
```

### 结论

`192.168.137.2` 是旧地址，当前不可作为默认连接目标。

## 问题 2：当前局域网地址可达但不稳定

### 当前树莓派 IP

曾通过 `ssh raspberrypi` 成功确认：

```text
hostname: raspberrypi
IP: 192.168.1.46 172.17.0.1 240e:305:1b86:2400:f638:e200:c55:bfe6
```

### 后续问题

后续本地连接时出现：

```text
ssh: Could not resolve hostname raspberrypi.local: Name or service not known
Connection closed by 192.168.1.46 port 22
```

这说明本地 SSH alias / mDNS / 局域网 SSH 通道并不总是可靠。

## 问题 3：`raspberrypi` SSH alias 指向 mDNS 名称

检查 SSH 配置：

```bash
ssh -G raspberrypi | grep -Ei '^(hostname|user|identityfile|port) '
```

输出：

```text
user pi
hostname raspberrypi.local
port 22
identityfile ~/.ssh/codex_raspberrypi
```

问题在于：

```text
raspberrypi.local
```

在当前本机/WSL 环境中有时无法解析，所以 `ssh raspberrypi` 会失败。

## 问题 4：腾讯云与树莓派互联链路不明显

用户说明：树莓派在局域网中，应该和腾讯云互联，刚刚应该还通信。

先检查腾讯云：

```bash
ssh tencent 'hostname; hostname -I; id'
```

结果：

```text
hostname: VM-0-11-opencloudos
IP: 10.0.0.11 172.17.0.1 172.18.0.1
user: root
```

从腾讯云直接 ping 树莓派局域网地址：

```bash
ssh tencent 'ping -c 2 -W 2 192.168.1.46'
```

结果：

```text
100% packet loss
```

这是正常的，因为 `192.168.1.46` 是树莓派所在局域网地址，腾讯云公网服务器通常不能直接访问该地址，除非存在 VPN、frp、反向 SSH、tailscale、zerotier 等互联机制。

## 发现：腾讯云上存在树莓派反向 SSH 入口

在腾讯云上检查监听端口和连接：

```bash
ssh tencent 'ss -lntp; ss -ntp | grep ESTAB || true'
```

发现：

```text
LISTEN 127.0.0.1:10022 users:(("sshd",...))
```

这说明腾讯云本地 `127.0.0.1:10022` 有一个 SSH 入口，很像反向隧道。

尝试通过腾讯云跳板连接：

```bash
ssh -J tencent \
  -i ~/.ssh/codex_raspberrypi \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=10 \
  -p 10022 \
  pi@127.0.0.1 \
  'hostname; hostname -I; uname -a'
```

结果成功：

```text
raspberrypi
192.168.1.46 172.17.0.1 240e:305:1b86:2400:f638:e200:c55:bfe6
Linux raspberrypi 6.12.25+rpt-rpi-2712 #1 SMP PREEMPT Debian 1:6.12.25-1+rpt1 (2025-04-30) aarch64 GNU/Linux
```

## 结论

当前确认可用的 fallback 连接链路是：

```text
本机 / WSL
-> ssh tencent
-> 腾讯云 127.0.0.1:10022
-> 反向 SSH
-> raspberrypi
```

可用命令：

```bash
ssh -J tencent \
  -i ~/.ssh/codex_raspberrypi \
  -p 10022 \
  pi@127.0.0.1
```

## 推荐：自适应 SSH 连接策略

以后不要只依赖单一路径。推荐连接顺序：

1. 尝试 mDNS：

```bash
ssh raspberrypi
```

2. 尝试当前局域网 IP：

```bash
ssh -i ~/.ssh/codex_raspberrypi pi@192.168.1.46
```

3. 如果局域网失败，走腾讯云反向 SSH：

```bash
ssh -J tencent \
  -i ~/.ssh/codex_raspberrypi \
  -p 10022 \
  pi@127.0.0.1
```

可以封装成脚本，例如：

```text
scripts/ssh_pi_auto.sh
```

伪逻辑：

```bash
try ssh raspberrypi
if failed:
  try ssh -i ~/.ssh/codex_raspberrypi pi@192.168.1.46
if failed:
  ssh -J tencent -i ~/.ssh/codex_raspberrypi -p 10022 pi@127.0.0.1
```

## 推荐：自适应 action controller 连接策略

实车动作控制器通常监听树莓派：

```text
http://192.168.1.46:8765
```

但如果局域网不通，可以通过腾讯云反向 SSH 链路建立本地隧道。

建议 fallback：

```bash
ssh -J tencent \
  -i ~/.ssh/codex_raspberrypi \
  -p 10022 \
  -L 18765:127.0.0.1:8765 \
  pi@127.0.0.1 \
  -N
```

然后本机访问：

```text
http://127.0.0.1:18765/health
```

这样 `audio_recognition` 的 `local_action_server` 可以使用：

```text
http://127.0.0.1:18765
```

推荐封装为：

```text
scripts/resolve_pi_action_server.py
```

逻辑：

```text
1. 测 http://192.168.1.46:8765/health
2. 如果成功，返回 http://192.168.1.46:8765
3. 如果失败，检查/启动 SSH tunnel 到 127.0.0.1:18765
4. 测 http://127.0.0.1:18765/health
5. 如果成功，返回 http://127.0.0.1:18765
6. 如果仍失败，明确报错，不执行实车动作
```

## 实车安全注意事项

即使 action controller 通过 fallback 连通，也不能直接执行真实移动。实车动作前仍需：

1. `/health` 正常；
2. 先发 `emergency_stop`；
3. 确认现场安全；
4. 对 `move_forward` 必须有新鲜 `front_distance` / sonar observation；
5. 动作结束后再发 `emergency_stop`。

## 当前可用命令摘要

### 连接腾讯云

```bash
ssh tencent
```

### 通过腾讯云连接树莓派

```bash
ssh -J tencent -i ~/.ssh/codex_raspberrypi -p 10022 pi@127.0.0.1
```

### 通过腾讯云执行树莓派命令

```bash
ssh -J tencent -i ~/.ssh/codex_raspberrypi -p 10022 pi@127.0.0.1 'hostname; hostname -I'
```

### 建立 action controller 本地隧道

```bash
ssh -J tencent \
  -i ~/.ssh/codex_raspberrypi \
  -p 10022 \
  -L 18765:127.0.0.1:8765 \
  pi@127.0.0.1 \
  -N
```

### 通过隧道检查 action controller

```bash
python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:18765/health', timeout=5) as r:
    print(r.status, r.read().decode())
PY
```

## 后续建议

建议实现：

```text
scripts/ssh_pi_auto.sh
scripts/resolve_pi_action_server.py
```

并在实车验证脚本中支持自动 action server 解析，避免下次再次因为 mDNS、局域网 IP、腾讯云反向隧道三种路径混用而中断验证。
