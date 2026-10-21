#!/usr/bin/env python3
"""
CPU cost per frame for NRISamples, Metal vs Vulkan.

HOW IT WORKS:
For every sample and API pair and every repetition, the script runs the sample
twice. One is a short run (fewer frames), and the other is a long run (many frames). It reads the CPU
time the operating system charged to the child process (user + system time,
all threads) and the wall-clock time of each run.

I used the formula below to cancel one time startup costs. So all that is left is the steady state cost per frame
per-frame cost = (long - short) / (long_frames - short_frames)

SCRIPT RULES:
- pso_cache.bin is deleted before every run (Metal and Vulkan share the name).
- --alwaysActive is passed so that an unfocused window does not stall the frame loop.
- vsync is left off (the sample default).
- A run is excluded if:
    1) the exit code is not 0
    2) "Shutting down" was not printed
    3) a Vulkan run printed "Validation Enabled" (because I noticed on my setup that the validation layer inflates CPU time)

USAGE:
python3 Scripts/Benchmark/benchmark.py
python3 Scripts/Benchmark/benchmark.py --reps 2 --short 100 --long 400 --samples Triangle
"""

import argparse
import csv
import datetime
import os
import platform
import resource
import statistics
import subprocess
import sys
import time


def run_once(exe, api, frames, cwd, extra_args, timeout):
    """Run one sample once. Returns a dict with timings and validity."""
    cache = os.path.join(cwd, "pso_cache.bin")
    if os.path.exists(cache):
        os.remove(cache)

    cmd = [exe, "--api=" + api, "--frameNum=" + str(frames), "--alwaysActive"] + extra_args

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, timeout=timeout)
        output, code = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired:
        output, code = "", -999
    wall = time.perf_counter() - t0
    after = resource.getrusage(resource.RUSAGE_CHILDREN)

    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)

    problems = []
    if code != 0:
        problems.append("exit code %d" % code)
    if "Shutting down" not in output:
        problems.append("no 'Shutting down' line")
    if api == "VULKAN" and "Validation Enabled" in output:
        problems.append("Vulkan validation layer was on")

    return {"wall_s": wall, "cpu_s": cpu, "exit": code,
            "valid": not problems, "problems": "; ".join(problems)}


def spread(values):
    """median, min, max, stdev, interquartile range."""
    med = statistics.median(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    if len(values) >= 4:
        q = statistics.quantiles(values, n=4)
        iqr = q[2] - q[0]
    else:
        iqr = max(values) - min(values)
    return med, min(values), max(values), sd, iqr


def machine_info(cwd):
    lines = ["date: " + datetime.datetime.now().isoformat(timespec="seconds"),
             "platform: " + platform.platform(),
             "python: " + platform.python_version()]
    try:
        brand = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                               stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
        lines.append("cpu: " + brand)
        power = subprocess.run(["pmset", "-g", "batt"], stdout=subprocess.PIPE,
                               universal_newlines=True).stdout.strip().replace("\n", " | ")
        lines.append("power: " + power)
        for name, path in (("NRISamples", cwd),
                           ("NRIFramework", os.path.join(cwd, "External", "NRIFramework")),
                           ("NRI", os.path.join(cwd, "External", "NRIFramework", "External", "NRI"))):
            rev = subprocess.run(["git", "-C", path, "rev-parse", "--short", "HEAD"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 universal_newlines=True).stdout.strip()
            lines.append("git %s: %s" % (name, rev or "unknown"))
    except OSError:
        pass
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bin-dir", default="_Bin/Release", help="folder with sample executables")
    ap.add_argument("--samples", nargs="+", default=["Triangle", "SceneViewer"])
    ap.add_argument("--apis", nargs="+", default=["METAL", "VULKAN"])
    ap.add_argument("--reps", type=int, default=10, help="repetitions per sample and API")
    ap.add_argument("--short", type=int, default=300, help="frames in the short run")
    ap.add_argument("--long", type=int, default=2000, help="frames in the long run")
    ap.add_argument("--timeout", type=int, default=300, help="seconds before a run is killed")
    ap.add_argument("--out", default="Scripts/Benchmark/results", help="output folder")
    args = ap.parse_args()

    if args.long <= args.short:
        sys.exit("--long must be larger than --short")

    cwd = os.getcwd()
    bin_dir = os.path.join(cwd, args.bin_dir)
    for s in args.samples:
        if not os.path.exists(os.path.join(bin_dir, s)):
            sys.exit("Cannot find %s. Run this from the NRISamples root after building." % os.path.join(bin_dir, s))
    if "VULKAN" in args.apis and not os.environ.get("VULKAN_SDK"):
        print("WARNING: VULKAN_SDK is not set. Run: source ~/VulkanSDK/<version>/setup-env.sh")

    try: # does it need to be AC Power? My results differed based on whether the laptop was plugged in
        batt = subprocess.run(["pmset", "-g", "batt"], stdout=subprocess.PIPE, universal_newlines=True).stdout
        if "Battery Power" in batt:
            sys.exit("The Mac is on battery power. Plug in the charger and run again.") # not sure if this is neccessary TBH
    except OSError:
        pass

    os.makedirs(os.path.join(cwd, args.out), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_path = os.path.join(cwd, args.out, "raw-%s.csv" % stamp)
    sum_path = os.path.join(cwd, args.out, "summary-%s.txt" % stamp)

    pairs = [(s, a) for s in args.samples for a in args.apis]
    per_frame = dict((p, {"cpu": [], "wall": []}) for p in pairs)
    invalid = dict((p, 0) for p in pairs)
    extra = []

    print("Hands off the keyboard and mouse, and do not cover the windows, while this runs.")
    print("Plan: %d reps x %d pairs x 2 runs (+ warm-ups)" % (args.reps, len(pairs)))

    with open(raw_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rep", "sample", "api", "kind", "frames", "wall_s", "cpu_s", "exit", "valid", "problems"])

        # warmup: one throw away run per pair so files are in the OS cache.
        for sample, api in pairs:
            exe = os.path.join(bin_dir, sample)
            r = run_once(exe, api, args.short, cwd, extra, args.timeout)
            print("warm-up %-12s %-7s %s" % (sample, api, "ok" if r["valid"] else "PROBLEM: " + r["problems"]))

        # interleave APIs inside each rep
        # hits both APIs the same way
        for rep in range(1, args.reps + 1):
            for sample, api in pairs:
                exe = os.path.join(bin_dir, sample)
                short = run_once(exe, api, args.short, cwd, extra, args.timeout)
                long_ = run_once(exe, api, args.long, cwd, extra, args.timeout)
                for kind, frames, r in (("short", args.short, short), ("long", args.long, long_)):
                    w.writerow([rep, sample, api, kind, frames, "%.4f" % r["wall_s"], "%.4f" % r["cpu_s"],
                                r["exit"], r["valid"], r["problems"]])
                f.flush()
                if short["valid"] and long_["valid"]:
                    df = args.long - args.short
                    cpu_ms = (long_["cpu_s"] - short["cpu_s"]) / df * 1000.0
                    wall_ms = (long_["wall_s"] - short["wall_s"]) / df * 1000.0
                    per_frame[(sample, api)]["cpu"].append(cpu_ms)
                    per_frame[(sample, api)]["wall"].append(wall_ms)
                    print("rep %2d %-12s %-7s cpu %.4f ms/frame   wall %.4f ms/frame" % (rep, sample, api, cpu_ms, wall_ms))
                else:
                    invalid[(sample, api)] += 1
                    print("rep %2d %-12s %-7s INVALID: %s %s" % (rep, sample, api, short["problems"], long_["problems"]))

    out = machine_info(cwd)
    out.append("short=%d frames, long=%d frames, reps=%d" % (args.short, args.long, args.reps))
    out.append("")
    out.append("%-12s %-7s %-5s %8s %8s %8s %8s %8s  %s" % ("sample", "api", "kind", "median", "min", "max", "stdev", "iqr", "n (invalid)"))
    for sample, api in pairs:
        for kind, label in (("cpu", "CPU"), ("wall", "wall")):
            vals = per_frame[(sample, api)][kind]
            if not vals:
                out.append("%-12s %-7s %-5s  no valid runs" % (sample, api, label))
                continue
            med, lo, hi, sd, iqr = spread(vals)
            out.append("%-12s %-7s %-5s %8.4f %8.4f %8.4f %8.4f %8.4f  %d (%d)" % (
                sample, api, label, med, lo, hi, sd, iqr, len(vals), invalid[(sample, api)]))
    out.append("")
    out.append("All values are milliseconds per frame.")

    text = "\n".join(out)
    print("\n" + text)
    with open(sum_path, "w") as f:
        f.write(text + "\n")
    print("\nSaved:\n  " + raw_path + "\n  " + sum_path)


if __name__ == "__main__":
    main()