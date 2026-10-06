"""Measure local process parallelism using exactly the same independent MC blocks.

Run from the project root: python scripts/benchmark_parallel.py
Each repetition creates a fresh pool; process startup, result transfer and pool
shutdown are included. This deliberately measures end-to-end request latency,
not the throughput of an already-running cluster. Slowdowns are retained.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from scipy.stats import t as student_t

from risklab.pricing import bs_price, mc_price


def price_block(task):
    """Top-level, spawn-picklable worker returning sufficient pair statistics."""
    return mc_price(100.0, 100.0, 1.0, 0.05, 0.2, n_paths=task["n_paths"],
                    seed=task["seed"], antithetic=True)


def combine_blocks(blocks):
    """Combine independent pair observations using within/between sums of squares.

    A block's SE equals sd(pair means)/sqrt(number of pairs). Reconstructing
    its centered sum of squares and including between-block mean differences
    gives the pooled sample variance. Averaging block standard errors would
    be incorrect. The final CI is a pointwise t interval for simulation error.
    """
    if not blocks:
        raise ValueError("at least one block is required")
    ns = np.array([b["independent_units"] for b in blocks], dtype=float)
    means = np.array([b["price"] for b in blocks], dtype=float)
    ses = np.array([b["standard_error"] for b in blocks], dtype=float)
    if not np.all(np.isfinite(np.concatenate([ns,means,ses]))) or np.any(ns < 2) or np.any(ses < 0):
        raise ValueError("blocks must have finite statistics and at least two independent units")
    n = int(np.sum(ns))
    mean = float(np.sum(ns * means) / n)
    within = (ns - 1) * ns * ses ** 2
    between = ns * (means - mean) ** 2
    variance = float(np.sum(within + between) / (n - 1))
    se = float(np.sqrt(variance / n))
    half = float(student_t.ppf(.975, n - 1) * se)
    return {"price": mean, "standard_error": se, "ci_low": mean-half,
            "ci_high": mean+half, "n_paths": int(sum(b["n_paths"] for b in blocks)),
            "independent_units": n}


def make_tasks(n_paths, blocks, seed):
    for value, label in [(n_paths,"n_paths"),(blocks,"blocks")]:
        if isinstance(value,bool) or not isinstance(value,int) or value < 1:
            raise ValueError(f"{label} must be a positive integer")
    if n_paths % (2 * blocks) or n_paths // blocks < 4:
        raise ValueError("n_paths must be divisible by 2*blocks and each block requires >=4 paths")
    sequence = np.random.SeedSequence(seed)
    children = sequence.spawn(blocks)
    return [{"n_paths":n_paths//blocks,
             "seed":int(child.generate_state(1,dtype=np.uint64)[0])} for child in children]


def run_benchmark(n_paths=2000000, blocks=8, repetitions=3, workers=(1,2,4), seed=741927):
    """Fixed work and substreams across modes/repetitions; only time changes."""
    tasks = make_tasks(n_paths,blocks,seed)
    if isinstance(repetitions,bool) or not isinstance(repetitions,int) or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    if not workers or 1 not in workers or any(isinstance(w,bool) or not isinstance(w,int) or w < 1 for w in workers):
        raise ValueError("workers must include serial mode 1 and contain positive integers")
    if len(set(workers)) != len(workers):
        raise ValueError("workers cannot contain duplicates")
    rows = []
    reference = None
    for repetition in range(repetitions):
        # Rotate mode order to reduce simple order/thermal bias; retain every run.
        offset = repetition % len(workers)
        mode_order = list(workers[offset:])+list(workers[:offset])
        for worker_count in mode_order:
            start = time.perf_counter()
            if worker_count == 1:
                results = [price_block(task) for task in tasks]
            else:
                with ProcessPoolExecutor(max_workers=worker_count,
                                         mp_context=multiprocessing.get_context("spawn")) as pool:
                    results = list(pool.map(price_block,tasks))
            summary = combine_blocks(results)
            elapsed = time.perf_counter()-start
            if reference is None:
                reference = summary
            if summary != reference:
                raise RuntimeError("same seeded blocks produced unequal serial/parallel statistics")
            rows.append({"repetition":repetition+1,"workers":worker_count,
                         "mode":"serial" if worker_count==1 else "process_pool",
                         "elapsed_seconds":elapsed,**summary})
    mode_summary = []
    serial_median = float(np.median([r["elapsed_seconds"] for r in rows if r["workers"]==1]))
    for w in workers:
        durations = np.array([r["elapsed_seconds"] for r in rows if r["workers"]==w])
        median = float(np.median(durations))
        mode_summary.append({"workers":w,"repetitions":repetitions,
                             "median_seconds":median,"min_seconds":float(durations.min()),
                             "max_seconds":float(durations.max()),
                             "speedup_vs_serial_median":serial_median/median})
    definition = {"total_paths":n_paths,"independent_pair_units":n_paths//2,"blocks":blocks,
                  "seed":seed,"tasks":tasks,"repetitions":repetitions,"workers":list(workers),
                  "parameters":{"spot":100,"strike":100,"maturity":1,"rate":.05,"vol":.2},
                  "includes":"wall time includes task execution, startup, result collection, pool shutdown and statistic combination",
                  "independence":"SeedSequence child streams; each antithetic pair average is one independent observation",
                  "repeat_interpretation":"Repeated timings use identical random blocks; they are not independent pricing replications"}
    encoded = json.dumps(definition,sort_keys=True,separators=(",",":")).encode()
    return {"protocol":definition,"protocol_sha256":hashlib.sha256(encoded).hexdigest(),
            "estimator":reference,"analytic_price":bs_price(100,100,1,.05,.2),
            "serial_parallel_statistics_exactly_equal":True,"timings":rows,"summary":mode_summary,
            "environment":{"python":platform.python_version(),"platform":platform.platform(),
                           "logical_cpus":os.cpu_count(),"numpy":np.__version__,"start_method":"spawn"},
            "limitations":["One local machine, three repetitions by default, no cluster or HPC scalability claim.",
                           "Vectorized NumPy already does efficient per-block work; startup may dominate.",
                           "Concurrent machine activity and timing variance remain uncontrolled.",
                           "The number of workers is not the number of independent observations.",
                           "Repeated timings do not multiply the independent pricing sample size."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-paths",type=int,default=2000000)
    parser.add_argument("--blocks",type=int,default=8)
    parser.add_argument("--repetitions",type=int,default=3)
    parser.add_argument("--seed",type=int,default=741927)
    parser.add_argument("--output",type=Path,default=ROOT/"results")
    args = parser.parse_args()
    result = run_benchmark(args.n_paths,args.blocks,args.repetitions,seed=args.seed)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"parallel_benchmark.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    with (args.output/"parallel_benchmark.csv").open("w",newline="",encoding="utf-8") as file:
        writer = csv.DictWriter(file,fieldnames=list(result["timings"][0]))
        writer.writeheader()
        writer.writerows(result["timings"])
    print(json.dumps({"summary":result["summary"],"estimator":result["estimator"]},indent=2))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
