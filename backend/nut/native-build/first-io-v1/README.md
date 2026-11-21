# Optional first-IO source profile

This opt-in profile applies three frozen native source changes and two Python
runtime changes to the public post-HIDAPI-0.16 source checkpoint and the
qualified nine-module runtime. It is source-only. The historical supervisor,
default profiles, vendor files, build inputs, app, and hardware remain outside
the change.

Set `CHECKOUT`, `POST016`, `QUALIFIED_RUNTIME`, and `WORK_PARENT` to absolute
paths. `POST016` is the already admitted post-0.16 NUT tree, including
`drivers/hidapi-0.16.0/`. `QUALIFIED_RUNTIME` is the nine-module directory
after the public 90-second qualification patch. Use the public procedure in
[`docs/APP_SOURCE_DELIVERY.md`](../../../../docs/APP_SOURCE_DELIVERY.md) to
stage that base and verify all nine pins first. Use a reviewed macOS Python
3.15.2 executable as `HOST_PYTHON`. The recipe preflights every source and
vendor row and every runtime row before creating the private scratch stage.

The manifest pin in the command is the SHA-256 of this profile's
`manifest.json`. Run this block from a private shell. It stages only the 190
project files, eight vendor files, and nine runtime modules; validates complete
canonical maps before and after patching; and runs each exact patch argument
vector under the unchanged pinned supervisor with the historical
30-second/1-MiB bounds.

```sh
"$HOST_PYTHON" -I -S -B - "$CHECKOUT" "$POST016" "$QUALIFIED_RUNTIME" "$WORK_PARENT" "a9350f0674a7f2aa26b61ad186e37d9d77204fa7ab672a65c4dadf066907c064" <<'PY'
import hashlib, importlib.util, json, os, shutil, stat, tempfile
from pathlib import Path
from threading import Event
import sys

if len(sys.argv) != 6:
    raise SystemExit('expected five path and manifest-pin arguments')
checkout, source, runtime, parent = map(Path, sys.argv[1:5])
manifest_pin = sys.argv[5]

def root_without_links(root):
    if not root.is_absolute() or '..' in root.parts:
        raise SystemExit('input path must be canonical and absolute')
    root = root.absolute()
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        if stat.S_ISLNK(current.lstat().st_mode):
            raise SystemExit('symlinked root component: ' + str(current))
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise SystemExit('input root is not a directory')
    resolved = root.resolve(strict=True)
    if resolved != root:
        raise SystemExit('input path is not canonical')
    return resolved

checkout_root = root_without_links(checkout)
profile = checkout / 'backend/nut/native-build/first-io-v1'
manifest_path = checkout_root / 'backend/nut/native-build/first-io-v1/manifest.json'

def sha(path):
    path = Path(path).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise SystemExit('symlink in hashed input: ' + str(path))
    if path.stat().st_size > 4 * 1024 * 1024:
        raise SystemExit('input file exceeds 4-MiB read limit')
    if not stat.S_ISREG(path.lstat().st_mode):
        raise SystemExit('hashed input is not a regular file: ' + str(path))
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

if sha(manifest_path) != manifest_pin:
    raise SystemExit('profile manifest hash mismatch')
manifest = json.loads(manifest_path.read_bytes())

def map_sha(rows):
    raw = json.dumps(rows, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=True).encode('ascii') + b'\n'
    return hashlib.sha256(raw).hexdigest()

def regular(root, name):
    root = root.absolute()
    path = root
    for part in Path(name).parts:
        if part in ('', '.', '..'):
            raise SystemExit('unsafe manifest path: ' + name)
        path /= part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise SystemExit('symlink in input path: ' + name)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise SystemExit('input is not a regular file: ' + name)
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise SystemExit('input escapes root: ' + name)
    return path

source_root = root_without_links(source)
runtime_root = root_without_links(runtime)
parent_root = root_without_links(parent)
if tuple(__import__('sys').version_info[:3]) != (3, 15, 2):
    raise SystemExit('HOST_PYTHON must be version 3.15.2')
if os.stat(parent_root).st_uid != os.getuid() or stat.S_IMODE(parent_root.stat().st_mode) & 0o077:
    raise SystemExit('WORK_PARENT must be owned by this user and private (mode 0700 or stricter)')
for input_root in (checkout_root, source_root, runtime_root):
    if parent_root == input_root or parent_root.is_relative_to(input_root) or input_root.is_relative_to(parent_root):
        raise SystemExit('WORK_PARENT must not overlap a source or checkout tree')

def assert_hash(path, expected, label):
    if sha(path) != expected:
        raise SystemExit(label + ' hash mismatch')

assert_hash(profile / 'manifest.json', manifest_pin, 'profile manifest')
for name, expected in manifest['payloads'].items():
    assert_hash(profile / name, expected, name)
native_lock_path = checkout / 'backend/nut/native-build/hidapi-0.16/manifest.json'
assert_hash(native_lock_path, manifest['qualification']['base_manifest_sha256'], 'native base manifest')
native_lock = json.loads(native_lock_path.read_bytes())
native_rows = native_lock['post_hidapi_016_sha256']
vendor_rows = {row['path']: row['sha256'] for row in native_lock['hidapi']['files']}
if len(native_rows) != 190 or len(vendor_rows) != 8:
    raise SystemExit('native or vendor inventory count mismatch')
if sum(regular(source_root, name).stat().st_size for name in native_rows) > 128 * 1024 * 1024:
    raise SystemExit('native input exceeds 128-MiB total read limit')
actual_native = {name: sha(regular(source_root, name)) for name in sorted(native_rows)}
if actual_native != native_rows or map_sha(actual_native) != manifest['qualification']['native_base_map_sha256']:
    raise SystemExit('complete 190-file native base map mismatch')
for name, row in manifest['native_delta'].items():
    if actual_native.get(name) != row['before']:
        raise SystemExit('native delta preimage mismatch: ' + name)
vendor_root_name = 'drivers/hidapi-0.16.0'
vendor_source_root = root_without_links(source_root / vendor_root_name)
if sum(regular(vendor_source_root, name).stat().st_size for name in vendor_rows) > 128 * 1024 * 1024:
    raise SystemExit('vendor input exceeds 128-MiB total read limit')
actual_vendor = {name: sha(regular(vendor_source_root, name)) for name in sorted(vendor_rows)}
if actual_vendor != vendor_rows:
    raise SystemExit('complete eight-file vendor map mismatch')

runtime_manifest = checkout / 'backend/nut/qualification/module-sha256.json'
assert_hash(runtime_manifest, manifest['qualification']['runtime_base_manifest_sha256'], 'runtime base manifest')
assert_hash(checkout / 'backend/nut/qualification/smc1500i-90s.patch', manifest['qualification']['runtime_qualification_patch_sha256'], 'qualification patch')
runtime_rows = json.loads(runtime_manifest.read_bytes())
if len(runtime_rows) != 9:
    raise SystemExit('runtime inventory count mismatch')
if sum(regular(runtime_root, name).stat().st_size for name in runtime_rows) > 128 * 1024 * 1024:
    raise SystemExit('runtime input exceeds 128-MiB total read limit')
actual_runtime = {name: sha(regular(runtime_root, name)) for name in sorted(runtime_rows)}
if actual_runtime != runtime_rows or map_sha(actual_runtime) != manifest['qualification']['runtime_qualified_base_map_sha256']:
    raise SystemExit('complete nine-file qualified runtime map mismatch')
for name, row in manifest['runtime_delta'].items():
    if actual_runtime.get(name) != row['before']:
        raise SystemExit('runtime delta preimage mismatch: ' + name)

# Only after every complete input map passes, create the isolated staged copy.
stage = Path(tempfile.mkdtemp(prefix='first-io-v1.', dir=parent_root))
stage.chmod(0o700)
staged_source, staged_runtime = stage / 'source', stage / 'runtime'
staged_source.mkdir(mode=0o700); staged_runtime.mkdir(mode=0o700)
(stage / 'logs').mkdir(mode=0o700)
def copy_rows(src, dst, rows):
    for name in sorted(rows):
        origin = regular(src, name)
        target = dst / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target, follow_symlinks=False)
        target.chmod(stat.S_IMODE(origin.stat().st_mode))
copy_rows(source_root, staged_source, native_rows)
copy_rows(vendor_source_root, staged_source / vendor_root_name, vendor_rows)
copy_rows(runtime_root, staged_runtime, runtime_rows)

def inventory(root):
    result = set()
    for path in root.rglob('*'):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise SystemExit('staged symlink rejected')
        if stat.S_ISREG(info.st_mode):
            result.add(path.relative_to(root).as_posix())
        elif not stat.S_ISDIR(info.st_mode):
            raise SystemExit('unexpected staged object')
    return result

expected_source = set(native_rows) | {vendor_root_name + '/' + name for name in vendor_rows}
if inventory(staged_source) != expected_source or inventory(staged_runtime) != set(runtime_rows):
    raise SystemExit('staged inventory mismatch')
staged_native = {name: sha(regular(staged_source, name)) for name in sorted(native_rows)}
staged_vendor = {name: sha(regular(staged_source / vendor_root_name, name)) for name in sorted(vendor_rows)}
staged_runtime_base = {name: sha(regular(staged_runtime, name)) for name in sorted(runtime_rows)}
if (staged_native != actual_native or staged_vendor != actual_vendor
        or staged_runtime_base != actual_runtime):
    raise SystemExit('staged preimage maps differ from preflight inputs')

supervisor_path = checkout / 'backend/nut/process_deadline.py'
assert_hash(supervisor_path, '81cf0d70708042810f7f26f42e2306cb89e83d4e306063dc1a5648b2eb883d4e', 'historical supervisor')
spec = importlib.util.spec_from_file_location('historical_process_deadline', supervisor_path)
supervisor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = supervisor
spec.loader.exec_module(supervisor)
patch = Path('/usr/bin/patch')

def apply(argv, name):
    assert_hash(supervisor_path, manifest['execution'].get('supervisor_sha256', '81cf0d70708042810f7f26f42e2306cb89e83d4e306063dc1a5648b2eb883d4e'), 'historical supervisor')
    result = supervisor.run_bounded(
        argv, executable_sha256=sha(patch), output_directory=stage / 'logs' / name,
        timeout_seconds=30, termination_grace_seconds=2,
        maximum_output_bytes=1_048_576, cancel_event=Event())
    if (result.status is not supervisor.RunStatus.EXITED
            or result.trigger is not supervisor.RunTrigger.COMPLETED
            or result.returncode != 0):
        raise SystemExit('bounded patch refused: ' + name)

native_patch = profile / 'native-first-io-v1.patch'
apply([str(patch), '--batch', '--forward', '--fuzz=0', '--no-backup-if-mismatch',
       '-p1', '-d', str(staged_source / 'drivers'), '-i', str(native_patch)], 'native')
native_post = dict(actual_native)
for name, row in manifest['native_delta'].items():
    native_post[name] = row['after']
if map_sha(native_post) != manifest['qualification']['native_postimage_map_sha256']:
    raise SystemExit('derived native postimage map pin mismatch')
now_native = {name: sha(regular(staged_source, name)) for name in sorted(native_rows)}
if now_native != native_post:
    raise SystemExit('complete 190-file native postimage mismatch')
if {name: sha(regular(staged_source / vendor_root_name, name)) for name in sorted(vendor_rows)} != vendor_rows:
    raise SystemExit('vendor input changed')

runtime_post = dict(actual_runtime)
for filename, patchname, logname in (
    ('cleanup_diagnostics.py', 'cleanup-diagnostics-first-io-v1.patch', 'cleanup'),
    ('process_deadline.py', 'process-deadline-first-io-v1.patch', 'deadline')):
    apply([str(patch), '--batch', '--forward', '--fuzz=0', '--no-backup-if-mismatch',
           '-i', str(profile / patchname), str(staged_runtime / filename)], logname)
    runtime_post[filename] = manifest['runtime_delta'][filename]['after']
    current = {name: sha(regular(staged_runtime, name)) for name in sorted(runtime_rows)}
    if current != runtime_post:
        raise SystemExit('complete nine-file runtime postimage mismatch')
if map_sha(runtime_post) != manifest['qualification']['runtime_postimage_map_sha256']:
    raise SystemExit('derived runtime postimage map pin mismatch')

if inventory(staged_source) != expected_source or inventory(staged_runtime) != set(runtime_rows):
    raise SystemExit('unexpected output, reject, backup, or staged member')
if ({name: sha(regular(staged_source, name)) for name in sorted(native_rows)} != native_post
        or {name: sha(regular(staged_source / vendor_root_name, name)) for name in sorted(vendor_rows)} != actual_vendor
        or {name: sha(regular(staged_runtime, name)) for name in sorted(runtime_rows)} != runtime_post):
    raise SystemExit('final complete source maps mismatch')
if sum(actual_native[n] != now_native[n] for n in native_rows) != 3:
    raise SystemExit('native delta is not exactly three files')
if sum(actual_runtime[n] != runtime_post[n] for n in runtime_rows) != 2:
    raise SystemExit('runtime delta is not exactly two files')
if {name: sha(regular(source_root, name)) for name in sorted(native_rows)} != actual_native:
    raise SystemExit('original native input changed')
if {name: sha(regular(vendor_source_root, name)) for name in sorted(vendor_rows)} != actual_vendor:
    raise SystemExit('original vendor input changed')
if {name: sha(regular(runtime_root, name)) for name in sorted(runtime_rows)} != actual_runtime:
    raise SystemExit('original runtime input changed')
receipt = {
    'state': 'SOURCE_ONLY_PASS',
    'profile_manifest_sha256': manifest_pin,
    'native_base_manifest_sha256': manifest['qualification']['base_manifest_sha256'],
    'runtime_base_manifest_sha256': manifest['qualification']['runtime_base_manifest_sha256'],
    'qualification_patch_sha256': manifest['qualification']['runtime_qualification_patch_sha256'],
    'native_base_map_sha256': map_sha(actual_native),
    'native_postimage_map_sha256': map_sha(now_native),
    'runtime_base_map_sha256': map_sha(actual_runtime),
    'runtime_postimage_map_sha256': map_sha(runtime_post),
    'native_delta': manifest['native_delta'],
    'runtime_delta': manifest['runtime_delta'],
    'patch_sha256': manifest['payloads'],
    'counts': {'native_project': 190, 'native_changed': 3, 'native_unchanged': 187,
               'runtime': 9, 'runtime_changed': 2, 'runtime_unchanged': 7,
               'vendor': 8, 'vendor_changed': 0},
    'phase_outcomes': {'native_patch': 'EXITED_0', 'cleanup_patch': 'EXITED_0',
                       'deadline_patch': 'EXITED_0', 'complete_map_checks': 'PASS',
                       'vendor_unchanged': 'PASS', 'original_inputs_unchanged': 'PASS'},
    'build': 'NOT_RUN', 'signing': 'NOT_RUN', 'payload_execution': 'NOT_RUN'
}
receipt_path = stage / 'SOURCE_RECEIPT.json'
receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n', encoding='ascii')
receipt_path.chmod(0o600)
print('SOURCE_ONLY_PASS; build=NOT_RUN; signing=NOT_RUN; payload_execution=NOT_RUN')
PY
```

The patch process arguments in `apply` are the exact profile patch commands:
the native patch runs at `source/drivers` because its headers name driver
leaves; each Python patch names its verified staged target explicitly. Each
invocation has a fresh private output directory and uses the unchanged
30-second, 2-second termination grace, and 1-MiB combined output bounds.
`qualified_runtime_entrypoint_window_seconds` describes the already-qualified
90-second runtime entrypoint policy; it is not a first-IO timing window.

For negative controls, make fresh disposable copies of the input trees, alter
`drivers/dstate.c` in one copy and `bounded_stream_dispatch.py` in another,
then rerun the same block with each altered input. Both complete-map gates must
exit before scratch staging and before any patch or success result. A source
profile or `SOURCE_ONLY_PASS` does not establish build, signing, hardware, or
distribution qualification.
