# Mihomo User Bootstrap

一个面向个人服务器/桌面环境的 Mihomo 用户目录方案：

- 订阅更新和 geodata 更新使用 `systemd --user`
- 实际运行配置落在 `~/.config/mihomo/`
- 适合把系统级 `mihomo.service` 指向用户目录配置

本项目只包含 Mihomo 相关内容，不包含 OpenClaw 或其他上层应用。

## 项目结构

```text
mihomo-user-bootstrap/
  README.md
  .gitignore
  install-user.sh
  config/
    override.yaml
  env/
    subscription.env.example
    geodata.env.example
  scripts/
    update_mihomo_subscription.py
    update_mihomo_geodata.py
  systemd-user/
    mihomo-subscription-update.service
    mihomo-subscription-update.timer
    mihomo-geodata-update.service
    mihomo-geodata-update.timer
```

## 安装前提

你需要有一个可工作的 Mihomo 二进制，例如：

```bash
/opt/mihomo/mihomo
```

并且建议你的 `mihomo.service` 使用用户目录配置，例如：

```ini
ExecStart=/opt/mihomo/mihomo -d /home/<your-user>/.config/mihomo -f /home/<your-user>/.config/mihomo/config.yaml
```

如果你已经有现成的系统级 `mihomo.service`，只要确保它读取的是 `~/.config/mihomo/config.yaml` 即可。

## 安装

在项目目录中执行：

```bash
./install-user.sh
```

安装脚本会：

- 把脚本复制到 `~/.local/share/mihomo-user-bootstrap/scripts/`
- 把 systemd 用户单元复制到 `~/.config/systemd/user/`
- 在 `~/.config/mihomo/` 下创建模板文件（若不存在）
- 重新加载 `systemd --user`

## 初始化配置

首次安装后，编辑下面三个文件：

- `~/.config/mihomo/subscription.env`
- `~/.config/mihomo/geodata.env`
- `~/.config/mihomo/override.yaml`

至少要修改这些值：

- `SUBSCRIPTION_URL`
- `CONTROLLER_SECRET`
- `MIHOMO_BIN`

## 启用定时任务

```bash
systemctl --user enable --now mihomo-subscription-update.timer
systemctl --user enable --now mihomo-geodata-update.timer
```

## 手动执行一次

更新 geodata：

```bash
systemctl --user start mihomo-geodata-update.service
```

更新订阅并热重载：

```bash
systemctl --user start mihomo-subscription-update.service
```

查看日志：

```bash
journalctl --user -u mihomo-geodata-update.service -n 50 --no-pager
journalctl --user -u mihomo-subscription-update.service -n 50 --no-pager
```

## SSH / 局域网建议

为了避免 SSH、NAS、台式机、局域网服务误走代理，建议把私有网段加入：

- `tun.route-exclude-address`
- `prepend-rules` 里的 `DIRECT` 规则

默认模板已包含：

- `192.168.0.0/16`
- `10.0.0.0/8`
- `172.16.0.0/12`

如果你使用 Tailscale、WireGuard 或其他 VPN，还可以继续补：

- `100.64.0.0/10`
- 你的自定义 VPN 网段

## 安全提醒

- 不要提交真实 `subscription.env`
- 不要提交真实 `geodata.env`
- 不要提交运行时生成的 `config.yaml`、`subscription.yaml`、`cache.db`
- 不要提交真实 controller secret

