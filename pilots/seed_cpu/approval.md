# 本次联调的明确安全例外授权

2026-09-27，本会话用户在了解 `apparmor=unconfined` 会减少一层保护，以及只影响本次隔离联调容器后，回复：“好的，允许使用，请继续进行联调进程”。

适用范围：仅 `pilots/seed_cpu/` 的独立 CPU 联调，先无凭据无网络诊断，成功后继续 Seed 真实评测与同会话恢复。

保留：非 root、只读根目录、cap-drop ALL、no-new-privileges、限定 seccomp、Codex 工作区权限与命令网络限制。不授权特权容器、无限制 seccomp、关闭 Codex 沙箱、修改宿主/daemon 或操作其他题目的容器。本记录不向新题自动继承。
