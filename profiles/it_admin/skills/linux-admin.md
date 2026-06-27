# skills/linux-admin.md — Linux Server Administration

## Purpose

This skill provides Linux server administration knowledge for operations, troubleshooting, documentation, and safe automation.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Read-only checks may be recommended directly.

Service restarts, package installs/removals, firewall changes, user changes, permission changes, disk changes, reboot actions, and configuration writes require explicit human approval.

## Scope

Primary scope:

- Debian/Ubuntu/RHEL-family administration concepts
- systemd
- users, groups, sudo
- SSH
- package management
- storage and filesystems
- LVM
- networking
- firewalld, ufw, iptables, nftables concepts
- logs with journalctl and syslog
- cron and systemd timers
- SELinux/AppArmor basics
- performance troubleshooting
- Bash scripting
- Ansible compatibility

## Read-Only Commands

```bash
hostnamectl
uname -a
cat /etc/os-release
uptime
who
id
ip addr
ip route
ss -tulpn
systemctl status <service>
journalctl -u <service> --no-pager
df -h
lsblk
free -h
top
ps aux
sudo -l
```

## Change Commands Requiring Approval

Examples:

```bash
systemctl restart <service>
systemctl enable <service>
apt install <package>
apt remove <package>
dnf install <package>
useradd <user>
usermod <options> <user>
chmod
chown
ufw allow
firewall-cmd --add-service
reboot
shutdown
mkfs
fdisk
parted
lvremove
rm -rf
```

## Troubleshooting Areas

### Service Issues

Check:

- Service status
- Unit file
- Recent logs
- Listening ports
- Dependencies
- Permissions
- Disk space
- Config syntax

### Network Issues

Check:

- Interface state
- IP addressing
- Default route
- DNS resolution
- Local firewall
- Listening service
- Remote connectivity

### Storage Issues

Check:

- Filesystem usage
- Inode usage
- Mount state
- LVM state
- Disk errors
- Logs
- Application paths

## Output Expectations

When helping with Linux:

- Start with read-only diagnostics
- Distinguish distro-specific commands
- Label change commands clearly
- Include rollback where applicable
- Use dry-run options when available
- Avoid destructive commands unless explicitly approved and heavily warned
