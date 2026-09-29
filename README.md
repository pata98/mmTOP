# mmtop (Multi-Machine TOP)

A terminal monitor for GPU, CPU/RAM, disk capacity/IO, and network usage across multiple machines.

## Install

Install it only on the viewer machine (Python 3.9 or newer).

```bash
uv tool install git+https://github.com/pata98/mmTOP.git
```

## Configuration

Edit the project's `.config/config.toml`:

```toml
interval = 1.0
history_seconds = 300
default_metrics = ["gpu", "gpu_procs", "cpu_mem", "disk_usage", "net"]

[[machines]]
name = "machine0"
transport = "local"

[[machines]]
name = "machine1"
host = "alias_machine1"

[[machines]]
name = "machine2"
host = "alias_machine2"

```

- Run `mmtop --list` to list configured machines.
- SSH runs with `BatchMode=yes`, so **key-based authentication** (including ssh-agent) is required.

## SSH Config

Define each remote machine in `~/.ssh/config`. The `Host` alias must match the `host` value in `.config/config.toml`.

```sshconfig
Host alias_machine1
    HostName 192.168.0.11
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519

Host alias_machine2
    HostName 192.168.0.12
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
```



## Usage

```bash
mmtop
```

