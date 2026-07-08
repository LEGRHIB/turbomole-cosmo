from cosmors.models import StageResult
from cosmors.workdir import WorkDir


def _fn_factory(counter):
    def fn(stage_dir):
        counter.append(1)
        (stage_dir / "out.txt").write_text("hi")
        return StageResult(stage="s", status="done", workdir=str(stage_dir))
    return fn


def test_run_marks_done_and_resumes(tmp_path):
    wd = WorkDir(str(tmp_path), "mol")
    calls = []
    fn = _fn_factory(calls)

    r1 = wd.run_stage("s", fn, resume=True)
    assert r1.status == "done"
    assert wd.is_done("s")
    assert len(calls) == 1

    # second call skips because the .done stamp exists
    r2 = wd.run_stage("s", fn, resume=True)
    assert r2.status == "skipped"
    assert len(calls) == 1


def test_force_reruns(tmp_path):
    wd = WorkDir(str(tmp_path), "mol")
    calls = []
    fn = _fn_factory(calls)
    wd.run_stage("s", fn)
    wd.run_stage("s", fn, force=True)
    assert len(calls) == 2


def test_path_does_not_create(tmp_path):
    wd = WorkDir(str(tmp_path), "mol")
    p = wd.path("s")
    assert not p.exists()
