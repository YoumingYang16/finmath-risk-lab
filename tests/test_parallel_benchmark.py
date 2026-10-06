import numpy as np
import pytest

from scripts.benchmark_parallel import combine_blocks, make_tasks, run_benchmark


def test_combined_sample_variance_matches_raw_independent_units():
    # Unequal blocks with different means detect omission of between-block M2.
    samples = [np.array([1.,2.,4.]),np.array([10.,20.,25.,40.])]
    blocks = [{"price":float(x.mean()),"standard_error":float(x.std(ddof=1)/np.sqrt(x.size)),
               "independent_units":x.size,"n_paths":2*x.size} for x in samples]
    combined = combine_blocks(blocks)
    all_units = np.concatenate(samples)
    assert combined["price"] == pytest.approx(all_units.mean())
    assert combined["standard_error"] == pytest.approx(all_units.std(ddof=1)/np.sqrt(all_units.size))
    assert combined["independent_units"] == 7
    assert combined["n_paths"] == 14


def test_seed_substreams_are_distinct_and_repeatable():
    tasks = make_tasks(8000,4,178)
    assert tasks == make_tasks(8000,4,178)
    assert len({task["seed"] for task in tasks}) == 4
    assert sum(task["n_paths"] for task in tasks) == 8000


def test_spawn_process_mode_matches_exact_serial_statistics():
    result = run_benchmark(n_paths=8000,blocks=4,repetitions=1,workers=(1,2),seed=98)
    assert result["serial_parallel_statistics_exactly_equal"]
    assert len(result["timings"]) == 2
    assert result["estimator"]["independent_units"] == 4000
    assert all(row["elapsed_seconds"] > 0 for row in result["timings"])


@pytest.mark.parametrize("paths,blocks", [(100,3),(2,1),(100,0),(True,2)])
def test_invalid_chunk_shape_reject(paths,blocks):
    with pytest.raises(ValueError):
        make_tasks(paths,blocks,1)
