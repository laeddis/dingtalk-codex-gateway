# Personal PC Agent Auto-Start

The PC agent runs on your personal computer and actively polls the public gateway. Your PC does not need a public IP and does not need inbound ports.

## Shared Setup

```bash
git clone git@github.com:laeddis/dingtalk-codex-gateway.git ~/dingtalk-codex-gateway
cd ~/dingtalk-codex-gateway
python3 -m pip install --user .
mkdir -p ~/.config
cp deploy/pc-agent.env.example ~/.config/dingtalk-codex-agent.env
chmod 600 ~/.config/dingtalk-codex-agent.env
editor ~/.config/dingtalk-codex-agent.env
```

Make sure `codex` works in the configured `AGENT_WORKSPACE_PATH` before installing auto-start:

```bash
cd "$(grep '^AGENT_WORKSPACE_PATH=' ~/.config/dingtalk-codex-agent.env | cut -d= -f2-)"
codex --help
```

Manual agent test:

```bash
~/.local/bin/dingtalk-codex-agent --env-file ~/.config/dingtalk-codex-agent.env
```

## Linux User systemd

Install and start for the current user:

```bash
mkdir -p ~/.config/systemd/user
cp ~/dingtalk-codex-gateway/deploy/pc-agent/dingtalk-codex-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dingtalk-codex-agent.service
systemctl --user status dingtalk-codex-agent.service
```

Start on boot even before opening a terminal session:

```bash
sudo loginctl enable-linger "$USER"
```

Logs:

```bash
journalctl --user -u dingtalk-codex-agent.service -f
```

Update after pulling new code:

```bash
cd ~/dingtalk-codex-gateway
git pull
python3 -m pip install --user .
systemctl --user restart dingtalk-codex-agent.service
```

## macOS launchd

Install and start for the current user:

```bash
mkdir -p ~/Library/LaunchAgents
cp ~/dingtalk-codex-gateway/deploy/pc-agent/com.laeddis.dingtalk-codex-agent.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.laeddis.dingtalk-codex-agent.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.laeddis.dingtalk-codex-agent.plist
launchctl start com.laeddis.dingtalk-codex-agent
```

Logs:

```bash
tail -f /tmp/dingtalk-codex-agent.out.log /tmp/dingtalk-codex-agent.err.log
```

Update after pulling new code:

```bash
cd ~/dingtalk-codex-gateway
git pull
python3 -m pip install --user .
launchctl kickstart -k gui/$(id -u)/com.laeddis.dingtalk-codex-agent
```
