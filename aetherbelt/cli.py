#!/usr/bin/env python3
"""aetherbelt.cli - the unified face of your our-own toolbelt.

Commands:
  aetherbelt status        show every our-own tool, its path, git head, liveness
  aetherbelt selfcheck     run each tool's smoke test, emit results to AETHERBUS
  aetherbelt bus           observe the shared AETHERBUS event spine
  aetherbelt dispatch <id> [args...]   run a tool by its short id

Design: local-first, zero paid deps. Each tool stays its own repo; aetherbelt
discovers them by path and routes. Everything that can be observed is emitted
to the bus so the constellation stays connected.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HOME = os.path.expanduser("~")

# --- our-own tools: id -> (repo dir, main script, self-check argv) ---
TOOLS = {
    "coinmoth":   ("coinmoth-cli", "coinmoth.py", ["scan", "just a self-check ping"]),
    "vault-lint": ("hybrid-vault-lint", "vault-lint.py", None),  # needs a vault arg
    "citewise":    ("our-own-citewise", "citewise.py", ["--self-check"]),
    "limen":       ("limen", "limen.py", None),
}

# --- AETHERBUS (silent fallback) ---
try:
    sys.path.insert(0, os.path.join(HOME, "aetherbus"))
    from aetherbus import emit as bus_emit, _read as bus_read
except Exception:  # noqa: BLE001
    def bus_emit(*_a, **_k):
        return False
    def bus_read(*_a, **_k):
        return []


def _tool_path(repo, main):
    return os.path.join(HOME, repo, main)


def discover():
    out = []
    for tid, (repo, main, _check) in TOOLS.items():
        p = _tool_path(repo, main)
        ok = os.path.exists(p)
        head = git_head(os.path.dirname(p)) if ok else "-"
        out.append({"id": tid, "path": p, "live": ok, "git": head})
    return out


def git_head(d):
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "-"
    except Exception:
        return "-"


def cmd_status(_args):
    tools = discover()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    bar = "=" * 58
    print(bar)
    print(f"  AETHERBELT  ·  unified toolbelt  ·  {now}")
    print(bar)
    print(f"  {'ID':<12} {'LIVE':<6} {'GIT':<10} PATH")
    print("-" * 58)
    for t in tools:
        print(f"  {t['id']:<12} {'YES' if t['live'] else 'NO':<6} {t['git']:<10} {t['path']}")
    print(bar)
    print(f"  {sum(1 for t in tools if t['live'])}/{len(tools)} tools present.  selfcheck: aetherbelt selfcheck")
    print(bar)
    return 0


def cmd_selfcheck(_args):
    tools = discover()
    results = []
    for t in tools:
        if not t["live"]:
            results.append((t["id"], "MISSING", None))
            bus_emit("aetherbelt", "selfcheck", f"{t['id']} MISSING",
                     level="warn", data={"tool": t["id"]})
            continue
        check = TOOLS[t["id"]][2]
        if not check:
            # vault-lint / limen need runtime args we won't fabricate; mark N/A
            results.append((t["id"], "N/A", None))
            bus_emit("aetherbelt", "selfcheck", f"{t['id']} present (manual check)",
                     level="info", data={"tool": t["id"]})
            continue
        cmd = [sys.executable, t["path"]] + check
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            ok = r.returncode == 0
            results.append((t["id"], "OK" if ok else "FAIL", r.returncode))
            bus_emit("aetherbelt", "selfcheck", f"{t['id']} {'OK' if ok else 'FAIL'}",
                     level="info" if ok else "alert",
                     data={"tool": t["id"], "rc": r.returncode})
        except Exception as e:  # noqa: BLE001
            results.append((t["id"], "ERROR", str(e)))
            bus_emit("aetherbelt", "selfcheck", f"{t['id']} ERROR: {e}",
                     level="alert", data={"tool": t["id"]})

    bar = "=" * 58
    print(bar)
    print("  AETHERBELT SELFCHECK")
    print(bar)
    for tid, state, _rc in results:
        print(f"  {tid:<12} {state}")
    print(bar)
    print("  results emitted to AETHERBUS. observe: aetherbelt bus")
    print(bar)
    return 0 if all(s in ("OK", "N/A") for _, s, _ in results) else 1


def cmd_bus(args):
    recs = list(bus_read([args.since] if args.since else None))
    shown = recs[-args.n:] if args.n else recs
    if not shown:
        print("(aetherbus: no events yet)")
        return 0
    print("=" * 58)
    print("  AETHERBUS  ·  shared event spine  ·  observe")
    print("=" * 58)
    for r in shown:
        extra = ""
        if r.get("data"):
            extra = "  " + json.dumps(r["data"], ensure_ascii=False)
        print(f"  {r['ts']}  {r['source']:<12} {r['type']:<9} [{r['level']}] {r['msg']}{extra}")
    print("=" * 58)
    print(f"  {len(shown)} event(s) shown.")
    print("=" * 58)
    return 0


def cmd_dispatch(args):
    if not args.rest:
        print("usage: aetherbelt dispatch <id> [args...]")
        return 2
    tid = args.rest[0]
    if tid not in TOOLS:
        print(f"unknown id '{tid}'. known: {', '.join(TOOLS)}")
        return 2
    t = TOOLS[tid]
    p = _tool_path(t[0], t[1])
    if not os.path.exists(p):
        print(f"{tid} not found at {p}")
        return 2
    rest = args.rest[1:]
    # coinmoth scan takes ONE free-text arg; if more than one token follows
    # 'scan', rejoin so a multi-word inbound DM stays whole.
    if tid == "coinmoth" and rest and rest[0] == "scan" and len(rest) > 2:
        rest = ["scan", " ".join(rest[1:])]
    cmd = [sys.executable, p] + rest
    print(f"> dispatching {tid}: {' '.join(cmd)}")
    try:
        rc = subprocess.run(cmd).returncode
        return rc
    except Exception as e:  # noqa: BLE001
        print(f"dispatch error: {e}")
        return 1


def main():
    ap = argparse.ArgumentParser(description="aetherbelt: unified local toolbelt for the Aether constellation")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status", help="show all our-own tools + liveness")
    sub.add_parser("selfcheck", help="smoke-test each tool, emit to bus")
    b = sub.add_parser("bus", help="observe the shared AETHERBUS spine")
    b.add_argument("-n", type=int, default=20)
    b.add_argument("--since", default=None)
    d = sub.add_parser("dispatch", help="run a tool by id")
    d.add_argument("rest", nargs=argparse.REMAINDER, help="<id> [args...]")
    args = ap.parse_args()
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "selfcheck":
        return cmd_selfcheck(args)
    if args.cmd == "bus":
        return cmd_bus(args)
    if args.cmd == "dispatch":
        return cmd_dispatch(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
