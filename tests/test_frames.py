"""MD front-end: synthetic frames -> RMSD cluster -> reps SDF."""
import pytest

pytest.importorskip("rdkit")

from cosmors.rdkit_utils import embed_from_smiles
from cosmors.stage4_md.frames import synthetic_frames, cluster_frames, write_reps


def test_synthetic_frames_count():
    seed = embed_from_smiles("CCO")
    frames = synthetic_frames(seed, 20, scale=0.5, seed=0)
    assert len(frames) == 20


def test_cluster_frames_reduces(tmp_path):
    seed = embed_from_smiles("CCO")
    frames = synthetic_frames(seed, 20, scale=0.6, seed=1)
    reps, report = cluster_frames(frames, rmsd_cutoff=1.0)
    assert report["n_in"] == 20
    assert 1 <= len(reps) <= 20
    assert report["n_kept"] == len(reps)
    write_reps(reps, str(tmp_path / "reps.sdf"))
    assert (tmp_path / "reps.sdf").exists()


def test_max_reps_cap():
    seed = embed_from_smiles("CCO")
    frames = synthetic_frames(seed, 30, scale=2.0, seed=2)   # spread out
    reps, _ = cluster_frames(frames, rmsd_cutoff=0.5, max_reps=5)
    assert len(reps) <= 5
