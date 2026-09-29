#!/usr/bin/env python3
# Standalone hardware sampler streamed to the viewer over ssh stdin.
# Must stay stdlib-only and Python 3.6 compatible: it runs on the remote
# machine's system interpreter without anything installed.
import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time

PROTOCOL_VERSION = 1
ALL_METRICS = ("gpu", "gpu_procs", "cpu_mem", "disk_usage", "disk_io", "net", "ib")

REAL_FSTYPES = {
    "ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs",
    "nfs", "nfs4", "cifs", "smb3", "smbfs", "ntfs", "ntfs3", "fuseblk", "vfat",
    "exfat", "lustre", "gpfs", "beegfs", "ceph", "glusterfs", "wekafs", "hfsplus",
}
IGNORED_FUSE = {"fuse.gvfsd-fuse", "fuse.portal", "fuse.lxcfs", "fuse.snapfuse", "fuse.doc"}
DEFAULT_EXCLUDE_MOUNTS = (
    "/snap/", "/var/lib/docker/", "/var/lib/containers/", "/var/lib/kubelet/",
    "/run/", "/proc", "/sys", "/dev",
)
DEFAULT_EXCLUDE_IFACES = (
    "lo", "docker", "veth", "br-", "virbr", "cni", "flannel", "cali", "kube-",
    "lxdbr", "lxc", "vxlan", "tunl", "genev",
)
EXCLUDE_BLOCK = ("loop", "ram", "zram", "sr", "fd", "nbd")
NA_VALUES = {"", "[N/A]", "N/A", "[Not Supported]", "Not Supported", "[Unknown Error]", "[Insufficient Permissions]"}

try:
    CLK_TCK = os.sysconf("SC_CLK_TCK")
    PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
except (ValueError, OSError, AttributeError):
    CLK_TCK = 100
    PAGE_SIZE = 4096


def read_text(path):
    with open(path, "r") as f:
        return f.read()


def to_num(value):
    value = value.strip()
    if value in NA_VALUES:
        return None
    try:
        if re.match(r"^-?\d+$", value):
            return int(value)
        return float(value)
    except ValueError:
        return None


def rate(cur, prev, dt):
    if prev is None or dt <= 0 or cur < prev:
        return None
    return (cur - prev) / dt


def matches_prefix(name, prefixes):
    for p in prefixes:
        if name == p or name.startswith(p):
            return True
    return False


# ---------------------------------------------------------------- parsers

def parse_proc_stat(text):
    """Return (cpu_total_fields, [per_core_fields])."""
    total = None
    cores = []
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        vals = [int(x) for x in parts[1:]]
        if parts[0] == "cpu":
            total = vals
        else:
            cores.append(vals)
    return total, cores


def cpu_busy_idle(vals):
    # user nice system idle iowait irq softirq steal (guest is already in user)
    vals = (vals + [0] * 8)[:8]
    idle = vals[3] + vals[4]
    return sum(vals) - idle, idle


def parse_meminfo(text):
    out = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.split()
        if not parts:
            continue
        try:
            val = int(parts[0])
        except ValueError:
            continue
        if len(parts) > 1 and parts[1] == "kB":
            val *= 1024
        out[key] = val
    return out


def parse_net_dev(text):
    out = {}
    for line in text.splitlines()[2:]:
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        fields = rest.split()
        if len(fields) < 16:
            continue
        out[name.strip()] = (int(fields[0]), int(fields[8]))
    return out


def parse_diskstats(text):
    """Return {name: (read_bytes, write_bytes, io_ticks_ms)}."""
    out = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) < 14:
            continue
        out[f[2]] = (int(f[5]) * 512, int(f[9]) * 512, int(f[12]))
    return out


def unescape_mount(path):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), path)


def parse_mounts(text, exclude=()):
    """Return [(device, mountpoint, fstype)] of real filesystems, one per device."""
    out = []
    seen_dev = set()
    for line in text.splitlines():
        f = line.split()
        if len(f) < 3:
            continue
        dev, mnt, fstype = unescape_mount(f[0]), unescape_mount(f[1]), f[2]
        if fstype not in REAL_FSTYPES and not (fstype.startswith("fuse.") and fstype not in IGNORED_FUSE):
            continue
        if mnt != "/" and matches_prefix(mnt, DEFAULT_EXCLUDE_MOUNTS + tuple(exclude)):
            continue
        if dev in seen_dev:
            continue
        seen_dev.add(dev)
        out.append((dev, mnt, fstype))
    return out


def parse_csv_row(line):
    return [c.strip() for c in line.split(",")]


# ---------------------------------------------------------------- GPU backends

GPU_CORE_FIELDS = [
    "index", "uuid", "name", "utilization.gpu", "utilization.memory",
    "memory.used", "memory.total", "temperature.gpu", "power.draw", "power.limit",
]
GPU_OPTIONAL_FIELDS = [
    "fan.speed", "clocks.sm", "clocks.mem", "clocks.max.sm", "clocks.max.mem",
    "pcie.link.gen.current", "pcie.link.width.current",
    "utilization.encoder", "utilization.decoder",
]
GPU_FIELD_KEYS = {
    "index": "index", "uuid": "uuid", "name": "name",
    "utilization.gpu": "util", "utilization.memory": "mem_util",
    "memory.used": "mem_used", "memory.total": "mem_total",
    "temperature.gpu": "temp", "power.draw": "power", "power.limit": "power_limit",
    "fan.speed": "fan", "clocks.sm": "clock_sm", "clocks.mem": "clock_mem",
    "clocks.max.sm": "clock_sm_max", "clocks.max.mem": "clock_mem_max",
    "pcie.link.gen.current": "pcie_gen", "pcie.link.width.current": "pcie_width",
    "utilization.encoder": "enc", "utilization.decoder": "dec",
}
MIB = 1024 * 1024


def parse_gpu_csv(text, fields):
    gpus = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        cols = parse_csv_row(line)
        if len(cols) != len(fields):
            continue
        g = {}
        for field, val in zip(fields, cols):
            key = GPU_FIELD_KEYS[field]
            if key in ("uuid", "name"):
                g[key] = val
            else:
                g[key] = to_num(val)
        for k in ("mem_used", "mem_total"):
            if g.get(k) is not None:
                g[k] = int(g[k] * MIB)
        gpus.append(g)
    return gpus


def parse_compute_apps(text):
    procs = []
    for line in text.strip().splitlines():
        cols = parse_csv_row(line)
        if len(cols) < 3:
            continue
        pid = to_num(cols[0])
        if pid is None:
            continue
        mem = to_num(cols[2])
        procs.append({"pid": int(pid), "gpu_uuid": cols[1], "gpu_mem": int(mem * MIB) if mem is not None else None})
    return procs


class SmiBackend(object):
    name = "nvidia-smi"

    def __init__(self):
        self.fields = GPU_CORE_FIELDS + GPU_OPTIONAL_FIELDS
        out, err, code = self._run(["--query-gpu=index", "--format=csv,noheader"])
        if code != 0:
            raise RuntimeError((err or out).strip().splitlines()[-1] if (err or out).strip() else "nvidia-smi failed")
        if self._query(self.fields) is None:
            self.fields = list(GPU_CORE_FIELDS)
            for f in GPU_OPTIONAL_FIELDS:
                if self._query(GPU_CORE_FIELDS + [f]) is not None:
                    self.fields.append(f)

    def _run(self, args):
        try:
            p = subprocess.Popen(["nvidia-smi"] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 universal_newlines=True)
        except OSError:
            raise RuntimeError("nvidia-smi not found")
        try:
            out, err = p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            raise RuntimeError("nvidia-smi timed out")
        return out, err, p.returncode

    def _query(self, fields):
        out, err, code = self._run(["--query-gpu=" + ",".join(fields), "--format=csv,noheader,nounits"])
        if code != 0:
            return None
        return out

    def gpus(self):
        out = self._query(self.fields)
        if out is None:
            raise RuntimeError("nvidia-smi query failed")
        return parse_gpu_csv(out, self.fields)

    def procs(self):
        out, err, code = self._run(["--query-compute-apps=pid,gpu_uuid,used_memory", "--format=csv,noheader,nounits"])
        if code != 0:
            raise RuntimeError("nvidia-smi compute-apps query failed")
        return parse_compute_apps(out)


class NvmlBackend(object):
    name = "nvml"

    def __init__(self):
        import pynvml
        self.N = pynvml
        pynvml.nvmlInit()
        self.handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
        self.last_ts = {}

    def _safe(self, fn, *args):
        try:
            return fn(*args)
        except Exception:
            return None

    @staticmethod
    def _str(v):
        return v.decode() if isinstance(v, bytes) else v

    def gpus(self):
        N = self.N
        out = []
        for i, h in enumerate(self.handles):
            g = {"index": i, "uuid": self._str(self._safe(N.nvmlDeviceGetUUID, h)),
                 "name": self._str(self._safe(N.nvmlDeviceGetName, h))}
            u = self._safe(N.nvmlDeviceGetUtilizationRates, h)
            g["util"] = u.gpu if u else None
            g["mem_util"] = u.memory if u else None
            m = self._safe(N.nvmlDeviceGetMemoryInfo, h)
            g["mem_used"] = m.used if m else None
            g["mem_total"] = m.total if m else None
            g["temp"] = self._safe(N.nvmlDeviceGetTemperature, h, N.NVML_TEMPERATURE_GPU)
            p = self._safe(N.nvmlDeviceGetPowerUsage, h)
            g["power"] = p / 1000.0 if p is not None else None
            pl = self._safe(N.nvmlDeviceGetEnforcedPowerLimit, h)
            g["power_limit"] = pl / 1000.0 if pl is not None else None
            g["fan"] = self._safe(N.nvmlDeviceGetFanSpeed, h)
            g["clock_sm"] = self._safe(N.nvmlDeviceGetClockInfo, h, N.NVML_CLOCK_SM)
            g["clock_mem"] = self._safe(N.nvmlDeviceGetClockInfo, h, N.NVML_CLOCK_MEM)
            g["clock_sm_max"] = self._safe(N.nvmlDeviceGetMaxClockInfo, h, N.NVML_CLOCK_SM)
            g["clock_mem_max"] = self._safe(N.nvmlDeviceGetMaxClockInfo, h, N.NVML_CLOCK_MEM)
            g["pcie_gen"] = self._safe(N.nvmlDeviceGetCurrPcieLinkGeneration, h)
            g["pcie_width"] = self._safe(N.nvmlDeviceGetCurrPcieLinkWidth, h)
            rx = self._safe(N.nvmlDeviceGetPcieThroughput, h, N.NVML_PCIE_UTIL_RX_BYTES)
            tx = self._safe(N.nvmlDeviceGetPcieThroughput, h, N.NVML_PCIE_UTIL_TX_BYTES)
            g["pcie_rx"] = rx * 1024 if rx is not None else None
            g["pcie_tx"] = tx * 1024 if tx is not None else None
            enc = self._safe(N.nvmlDeviceGetEncoderUtilization, h)
            dec = self._safe(N.nvmlDeviceGetDecoderUtilization, h)
            g["enc"] = enc[0] if enc else None
            g["dec"] = dec[0] if dec else None
            out.append(g)
        return out

    def procs(self):
        N = self.N
        out = []
        for i, h in enumerate(self.handles):
            uuid = self._str(self._safe(N.nvmlDeviceGetUUID, h))
            sm = {}
            samples = self._safe(N.nvmlDeviceGetProcessUtilization, h, self.last_ts.get(i, 0))
            if samples:
                for s in samples:
                    sm[s.pid] = s.smUtil
                    self.last_ts[i] = max(self.last_ts.get(i, 0), s.timeStamp)
            for p in self._safe(N.nvmlDeviceGetComputeRunningProcesses, h) or []:
                mem = getattr(p, "usedGpuMemory", None)
                out.append({"pid": p.pid, "gpu_uuid": uuid, "gpu_mem": mem if isinstance(mem, int) else None,
                            "sm": sm.get(p.pid)})
        return out


def make_gpu_backend():
    try:
        return NvmlBackend()
    except Exception:
        pass
    return SmiBackend()


# ---------------------------------------------------------------- collector

class Collector(object):
    def __init__(self, metrics, exclude_mounts=(), exclude_ifaces=()):
        self.metrics = set(metrics)
        self.exclude_mounts = tuple(exclude_mounts)
        self.exclude_ifaces = DEFAULT_EXCLUDE_IFACES + tuple(exclude_ifaces)
        self.prev_t = None
        self.prev_cpu = None
        self.prev_cores = None
        self.prev_net = {}
        self.prev_disk = {}
        self.prev_ib = {}
        self.prev_proc = {}
        self.users = {}
        self.hung_mounts = {}
        self.gpu = None
        self.gpu_error = None
        if self.metrics & {"gpu", "gpu_procs"}:
            try:
                self.gpu = make_gpu_backend()
            except Exception as e:
                self.gpu_error = str(e)

    def hello(self):
        return {
            "type": "hello", "v": PROTOCOL_VERSION, "hostname": socket.gethostname(),
            "metrics": sorted(self.metrics), "gpu_backend": self.gpu.name if self.gpu else None,
            "python": platform.python_version(), "kernel": platform.release(), "pid": os.getpid(),
        }

    def sample(self):
        now = time.time()
        dt = now - self.prev_t if self.prev_t else 0
        out = {"type": "sample", "v": PROTOCOL_VERSION, "ts": now, "errors": {}}
        try:
            out["uptime"] = float(read_text("/proc/uptime").split()[0])
        except (OSError, ValueError, IndexError):
            pass
        sections = [
            ("cpu_mem", self._cpu_mem), ("gpu", self._gpu), ("disk_usage", self._disk_usage),
            ("disk_io", self._disk_io), ("net", self._net), ("ib", self._ib),
        ]
        for metric, fn in sections:
            if metric == "gpu" and not self.metrics & {"gpu", "gpu_procs"}:
                continue
            if metric != "gpu" and metric not in self.metrics:
                continue
            try:
                fn(out, dt)
            except Exception as e:
                out["errors"][metric] = "%s: %s" % (type(e).__name__, e)
        self.prev_t = now
        return out

    def _cpu_mem(self, out, dt):
        total, cores = parse_proc_stat(read_text("/proc/stat"))

        def pct(cur, prev):
            if prev is None:
                return None
            b1, i1 = cpu_busy_idle(cur)
            b0, i0 = cpu_busy_idle(prev)
            d = (b1 - b0) + (i1 - i0)
            return 100.0 * (b1 - b0) / d if d > 0 else 0.0

        per_core = [pct(c, self.prev_cores[i] if self.prev_cores and i < len(self.prev_cores) else None)
                    for i, c in enumerate(cores)]
        load = [float(x) for x in read_text("/proc/loadavg").split()[:3]]
        out["cpu"] = {"pct": pct(total, self.prev_cpu), "per_core": per_core, "count": len(cores), "load": load}
        self.prev_cpu, self.prev_cores = total, cores
        mi = parse_meminfo(read_text("/proc/meminfo"))
        total_mem = mi.get("MemTotal", 0)
        avail = mi.get("MemAvailable", mi.get("MemFree", 0))
        out["mem"] = {
            "total": total_mem, "used": total_mem - avail, "available": avail,
            "swap_total": mi.get("SwapTotal", 0), "swap_used": mi.get("SwapTotal", 0) - mi.get("SwapFree", 0),
        }

    def _gpu(self, out, dt):
        if self.gpu is None:
            raise RuntimeError(self.gpu_error or "no GPU backend")
        gpus = self.gpu.gpus()
        if "gpu" in self.metrics:
            out["gpus"] = gpus
        if "gpu_procs" in self.metrics:
            try:
                out["procs"] = self._gpu_procs(gpus, dt)
            except Exception as e:
                out["errors"]["gpu_procs"] = "%s: %s" % (type(e).__name__, e)

    def _gpu_procs(self, gpus, dt):
        by_uuid = dict((g.get("uuid"), g.get("index")) for g in gpus)
        procs = self.gpu.procs()
        cur = {}
        for p in procs:
            pid = p["pid"]
            p["gpu_index"] = by_uuid.get(p.get("gpu_uuid"))
            p.setdefault("sm", None)
            p["user"], p["cmd"], p["cpu"], p["rss"] = None, None, None, None
            base = "/proc/%d/" % pid
            try:
                uid = None
                for line in read_text(base + "status").splitlines():
                    if line.startswith("Uid:"):
                        uid = int(line.split()[1])
                        break
                p["user"] = self._user(uid)
                cmd = read_text(base + "cmdline").replace("\0", " ").strip()
                p["cmd"] = cmd[:300] if cmd else read_text(base + "comm").strip()
                stat = read_text(base + "stat")
                fields = stat[stat.rfind(")") + 2:].split()
                ticks = int(fields[11]) + int(fields[12])
                cur[pid] = ticks
                prev = self.prev_proc.get(pid)
                if prev is not None and dt > 0:
                    p["cpu"] = 100.0 * (ticks - prev) / CLK_TCK / dt
                p["rss"] = int(read_text(base + "statm").split()[1]) * PAGE_SIZE
            except (OSError, ValueError, IndexError):
                pass
        self.prev_proc = cur
        procs.sort(key=lambda x: -(x.get("gpu_mem") or 0))
        return procs

    def _user(self, uid):
        if uid is None:
            return None
        if uid not in self.users:
            try:
                import pwd
                self.users[uid] = pwd.getpwuid(uid).pw_name
            except (KeyError, ImportError):
                self.users[uid] = str(uid)
        return self.users[uid]

    def _statvfs(self, path, timeout=1.0):
        t = self.hung_mounts.get(path)
        if t is not None:
            if t.is_alive():
                return None
            del self.hung_mounts[path]
        result = {}

        def work():
            try:
                result["v"] = os.statvfs(path)
            except OSError as e:
                result["e"] = e

        t = threading.Thread(target=work)
        t.daemon = True
        t.start()
        t.join(timeout)
        if t.is_alive():
            self.hung_mounts[path] = t
            return None
        return result.get("v")

    def _disk_usage(self, out, dt):
        disks = []
        for dev, mnt, fstype in parse_mounts(read_text("/proc/mounts"), self.exclude_mounts):
            st = self._statvfs(mnt)
            if st is None:
                if mnt in self.hung_mounts:
                    disks.append({"mount": mnt, "device": dev, "fstype": fstype, "total": None,
                                  "used": None, "avail": None, "stale": True})
                continue
            if st.f_blocks == 0:
                continue
            total = st.f_blocks * st.f_frsize
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
            disks.append({"mount": mnt, "device": dev, "fstype": fstype, "total": total,
                          "used": used, "avail": st.f_bavail * st.f_frsize})
        out["disks"] = disks

    def _disk_io(self, out, dt):
        try:
            block = set(os.listdir("/sys/block"))
        except OSError:
            block = None
        stats = parse_diskstats(read_text("/proc/diskstats"))
        res = []
        for name, (rd, wr, ticks) in stats.items():
            if block is not None and name not in block:
                continue
            if name.startswith(EXCLUDE_BLOCK) or re.match(r"mmcblk\d+(boot|rpmb)", name):
                continue
            prev = self.prev_disk.get(name)
            item = {"name": name, "read": None, "write": None, "busy": None}
            if prev:
                item["read"] = rate(rd, prev[0], dt)
                item["write"] = rate(wr, prev[1], dt)
                busy = rate(ticks, prev[2], dt)
                item["busy"] = min(100.0, busy / 10.0) if busy is not None else None
            res.append(item)
        self.prev_disk = stats
        res.sort(key=lambda x: x["name"])
        out["diskio"] = res

    def _net(self, out, dt):
        stats = parse_net_dev(read_text("/proc/net/dev"))
        res = []
        for name in sorted(stats):
            if matches_prefix(name, self.exclude_ifaces):
                continue
            rx, tx = stats[name]
            prev = self.prev_net.get(name)
            base = "/sys/class/net/%s/" % name
            speed = None
            up = None
            try:
                up = read_text(base + "operstate").strip() in ("up", "unknown")
                s = int(read_text(base + "speed").strip())
                speed = s if s > 0 else None
            except (OSError, ValueError):
                pass
            res.append({"name": name, "rx": rate(rx, prev[0], dt) if prev else None,
                        "tx": rate(tx, prev[1], dt) if prev else None, "speed": speed, "up": up,
                        "rx_total": rx, "tx_total": tx})
        self.prev_net = stats
        out["net"] = res

    def _ib(self, out, dt):
        root = "/sys/class/infiniband"
        res = []
        cur = {}
        devices = sorted(os.listdir(root)) if os.path.isdir(root) else []
        for dev in devices:
            ports_dir = os.path.join(root, dev, "ports")
            for port in sorted(os.listdir(ports_dir)):
                pdir = os.path.join(ports_dir, port)
                name = "%s/%s" % (dev, port)
                try:
                    rx = int(read_text(os.path.join(pdir, "counters", "port_rcv_data"))) * 4
                    tx = int(read_text(os.path.join(pdir, "counters", "port_xmit_data"))) * 4
                except (OSError, ValueError):
                    continue
                cur[name] = (rx, tx)
                prev = self.prev_ib.get(name)
                item = {"name": name, "rx": rate(rx, prev[0], dt) if prev else None,
                        "tx": rate(tx, prev[1], dt) if prev else None, "rate": None, "state": None}
                try:
                    item["rate"] = read_text(os.path.join(pdir, "rate")).strip()
                    item["state"] = read_text(os.path.join(pdir, "state")).strip().split(":")[-1].strip()
                except OSError:
                    pass
                res.append(item)
        self.prev_ib = cur
        out["ib"] = res


def emit(obj):
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def split_list(value):
    return [v for v in (value or "").split(",") if v]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mmtop-collector")
    ap.add_argument("--metrics", default=",".join(ALL_METRICS))
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--count", type=int, default=0, help="stop after N samples (0 = forever)")
    ap.add_argument("--exclude-mounts", default="")
    ap.add_argument("--exclude-ifaces", default="")
    args = ap.parse_args(argv)
    metrics = [m for m in split_list(args.metrics) if m in ALL_METRICS]
    interval = min(60.0, max(0.2, args.interval))
    try:
        c = Collector(metrics, split_list(args.exclude_mounts), split_list(args.exclude_ifaces))
        emit(c.hello())
        n = 0
        deadline = time.monotonic()
        while True:
            emit(c.sample())
            n += 1
            if args.count and n >= args.count:
                break
            deadline += interval
            delay = deadline - time.monotonic()
            if delay < 0:
                deadline = time.monotonic()
                delay = 0
            time.sleep(delay)
    except (BrokenPipeError, KeyboardInterrupt):
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
