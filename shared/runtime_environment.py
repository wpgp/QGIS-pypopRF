"""Stdlib-only environment contract for owned numerical child processes.

Importing this module never mutates the caller's environment. Dedicated CLI
entrypoints apply the thread caps before importing numerical libraries; GUI
adapters use a separate sanitized child environment.
"""
import os
from pathlib import Path
import hashlib


_ENGINE_BOOTSTRAP = """import hashlib,json,os,pathlib,runpy,sys
root=pathlib.Path(sys.argv[1]);expected=sys.argv[2];module=sys.argv[3]
assert root.is_absolute() and root.resolve()==root, 'Snapshot root must be canonical'
assert module in ('core.pypoprf','core.pypoprf.tools'), 'Unsupported engine entrypoint'
def safe(path):
    for part in (path,*path.parents):
        assert not part.is_symlink() and not (hasattr(part,'is_junction') and part.is_junction()), 'Snapshot links refused'
safe(root)
with (root/'.engine_snapshot.json').open('rb') as stream: raw=stream.read(256*1024+1)
assert len(raw)<=256*1024 and hashlib.sha256(raw).hexdigest()==expected, 'Snapshot manifest changed'
manifest=json.loads(raw);records=manifest['files']
assert manifest['schema_version']==1 and isinstance(records,dict) and 0<len(records)<=512, 'Invalid snapshot manifest'
total=0
for relative,record in records.items():
    path=pathlib.Path(relative)
    assert not path.is_absolute() and ':' not in relative and '\\\\' not in relative and '..' not in path.parts, 'Unsafe snapshot file'
    target=root/path;safe(target)
    with target.open('rb') as stream: data=stream.read(2*1024*1024+1)
    assert len(data)<=2*1024*1024 and len(data)==record['bytes'] and hashlib.sha256(data).hexdigest()==record['sha256'], 'Snapshot source changed'
    total+=len(data)
assert total<=8*1024*1024 and total==manifest['total_bytes'] and len(records)==manifest['file_count'], 'Snapshot limits mismatch'
expected_directories={parent.as_posix() for relative in records for parent in pathlib.Path(relative).parents if parent.as_posix()!='.'}
actual=set();actual_directories=set();pending=[root];entries_seen=0
while pending:
    directory=pending.pop()
    with os.scandir(directory) as entries:
        for entry in entries:
            entries_seen+=1
            assert entries_seen<=2048, 'Snapshot directory entry limit exceeded'
            path=pathlib.Path(entry.path);safe(path)
            relative=path.relative_to(root).as_posix()
            if entry.is_dir(follow_symlinks=False):
                assert relative in expected_directories, 'Snapshot directories changed'
                actual_directories.add(relative);pending.append(path)
            else: actual.add(relative)
assert actual==set(records)|{'.engine_snapshot.json'}, 'Snapshot resources changed'
assert actual_directories==expected_directories, 'Snapshot directories changed'
sys.path.insert(0,str(root))
from shared.runtime_environment import NATIVE_THREAD_LIMITS
os.environ.update(NATIVE_THREAD_LIMITS)
from importlib.metadata import version
assert isinstance(manifest['locked_dependencies'],dict) and manifest['locked_dependencies'], 'Empty snapshot dependency lock'
for name,expected_version in manifest['locked_dependencies'].items():
    assert version(name)==expected_version, 'Engine dependency versions do not match the frozen lock: '+name
sys._pypoprf_engine_snapshot={'manifest_sha256':expected,'file_count':manifest['file_count'],
                            'total_bytes':manifest['total_bytes'],'original_source_root':manifest['source_root']}
sys.argv=[module,*sys.argv[4:]]
runpy.run_module(module,run_name='__main__')
"""


NATIVE_THREAD_LIMITS = {
    "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}


def child_environment(python=None):
    """Return an independent environment, excluding host GIS/native overrides."""
    # -I is the first defense; also remove native QGIS/Qt/GDAL overrides.
    native_pools = set(NATIVE_THREAD_LIMITS)
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTHON", "QGIS", "QT_", "GDAL", "GEOS", "PROJ", "PIP_"))
           and key.upper() not in native_pools | {"VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV",
                                   "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"}}
    directories = [str(Path(python).resolve().parent)] if python else []
    if os.name == "nt":
        system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        directories += [str(system / "System32"), str(system)]
    else:
        directories += os.defpath.split(os.pathsep)
    env["PATH"] = os.pathsep.join(directories)
    env["PIP_CONFIG_FILE"] = os.devnull
    # Configured forest workers remain independent of each worker's native pool.
    env.update(NATIVE_THREAD_LIMITS)
    return env


def engine_arguments(snapshot_root, module, arguments):
    """Build an isolated, no-bytecode child bootstrap tied to frozen bytes."""
    if module not in {"core.pypoprf", "core.pypoprf.tools"}:
        raise ValueError("Only the analysis and tools engine entrypoints are supported")
    root = Path(snapshot_root).absolute()
    for part in (root, *root.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Snapshot links/junctions are refused")
    with (root / ".engine_snapshot.json").open("rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("Engine snapshot manifest is too large")
    return ["-I", "-B", "-X", "utf8", "-c", _ENGINE_BOOTSTRAP, str(root.resolve()),
            hashlib.sha256(raw).hexdigest(), module, *map(str, arguments)]
