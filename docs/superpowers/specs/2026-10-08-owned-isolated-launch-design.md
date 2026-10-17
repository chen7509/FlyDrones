# Owned isolated launch boundary

Scope: corrected offline Task4; user preapproved routine plans and inline work.
No live PX4/Gazebo, ODOMETRY, stream/parameter change or fusion is authorized.
Prior channel feasibility is sealed at7a2ccbd. The user goal remains trustworthy
VIO/PX4 and ultimately the complete policy/swarm comparison, not generic OS security.

## Choice

Implement one explicit subprocess wrapper using installed `unshare --user
--map-root-user --net`. Keep only loopback, no veth/proxy/host changes. Reuse
`supervise_worker`/GroupEvidence and declared_runtime_snapshot, not a new process
manager. Alternatives (host firewall, patched PX4 receiver) were rejected in the
channel report because they change host policy or fixed receiver semantics.

`launch_isolated(command, output, inventory, environment, timeout_s)` freezes the
exact vector/environment/declared files and actual parent namespace/UID/GID before
supervising the wrapper. Required singleton inventory roles: unshare, ip, python,
wrapper; dependencies and command inputs must be explicit nonempty roles. Paths
are absolute regular files. Wrapper role must equal the running source; command
executable must be declared. Use no shell or PATH executable discovery. No live
authority is inferred from arbitrary command contents or successful child exit.

## Worker gate

Before any command process: validate envelope/schema, actual parent identity
reference, different user+net namespace inodes, UID/GID0 mapped solely to recorded
nonroot parent UID/GID, same original process-group/session, and fresh worker PID.
Reject inherited sockets (including stdio); unknown extra inherited descriptors
are refused. Self `/proc/self/fd` enumeration's already-closed listing descriptor
is not an inherited descriptor. No hostile concurrent FD manipulation guarantee.

Record actual environment and compare it exactly to the declared environment.
No inherited LD_PRELOAD/PYTHON startup override. Wrapper uses Python isolated mode;
set HOME/PATH/LANG/LC_ALL explicitly for the synthetic runner. Command environment
is the exact declared dictionary. In-process imports still require a source/dependency
inventory; runtime closure remains false.

Before enabling lo require only the loopback interface; after enabling it require
UP, only loopback addresses, and only the installed loopback local routes with no
gateway/other device/default route. Preserve raw ip JSON. Each installed-ip call
has a 2s subprocess bound. Before command launch recheck namespace/process
identity, descriptor state and declared files, close the successful gate journal,
and only then spawn. A write/flush/close failure prevents command launch.

After command exit collect namespace/topology/files again, retain child exit and
any primary/post error. Identity/topology drift and nonzero child exit fail the
wrapper. The original-group supervisor still handles timeout, TERM/KILL, held
leader and reap. No supervisor or namespace fallback. No claim over escaped
descendants, malicious host/administrator, filesystem UNIX socket isolation,
atomic snapshots or crash-durable fsync. Hard kill may prevent worker post evidence;
parent post snapshot and supervisor evidence must remain independently attempted.

## Interfaces and evidence

Module tools/benchmark/isolated_namespace.py: pure `validate_observation(parent,
observation, ready)` plus real `observe(ip)`, worker `run_worker(envelope, output,
backend=None)` and parent `launch_isolated(...)`. Backend injection is solely
for deterministic unit tests, not a runtime CLI flag. Launch stores declaration,
parent/pre/post snapshots, worker observations/result and supervisor journal.
`isolated_launch_qualified` only covers this boundary; physical/network/fusion
authority flags always false. Qualification requires worker gate, exit0,
post stability and existing graceful cleanup, never just a ready file.

## Verification

Pure/synthetic tests: same namespace, bad UID/GID map, boolean/nonnumeric identities,
foreign interface/address/route, inherited socket/extra FD, environment drift,
changed executable/dependency, setup failure, journal partial/close failure,
identity drift before spawn, child exception/nonzero, post-read failure.
Behavioral RED before implementation, then regression of adjacent supervisor and
snapshot code. One prospective ordinary-process WSL harness: normal command,
child exit7, command timeout with TERM-resistant child, and same-host direct
worker refusal. No actual PX4/Gazebo/native estimator or repeat physical study.
Do not claim these cases qualify Gazebo discovery, runtime closure, cold PX4
filter ownership, uORB instance mapping or accepted TIMESYNC throughput.

Next after this boundary: first-reserved-reply bootstrap with existing observer,
decoder and reversible interval transaction; preserve25s/8s/2s/500accepted live
requirements. No further unrelated process governance.
