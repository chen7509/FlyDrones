$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$drive = $repoRoot.Substring(0, 1).ToLowerInvariant()
$linuxRoot = "/mnt/$drive/" + $repoRoot.Substring(3).Replace('\', '/')
$runDir = '/tmp/flydrones-px4-five-process-udp'

try {
    wsl -d Ubuntu -- env "FLYDRONES_PX4_RUN_DIR=$runDir" bash "$linuxRoot/tools/launch_px4_depth_swarm_wsl.sh"
    if ($LASTEXITCODE -ne 0) { throw "PX4/Gazebo distributed-swarm startup failed with exit code $LASTEXITCODE" }
    wsl -d Ubuntu -- env "PYTHONPATH=$linuxRoot/src" python3 "$linuxRoot/tools/run_distributed_px4_swarm.py" `
        --model "$linuxRoot/results/autonomous-forest-ppo-v1/autonomous-policy-numpy.npz" `
        --mission-timeout 70 `
        --process-timeout 150 `
        --peer-base-port 16770 `
        --output "$linuxRoot/results/px4-sitl-five-process-udp"
    if ($LASTEXITCODE -ne 0) { throw "Distributed learned SITL acceptance failed with exit code $LASTEXITCODE" }
}
finally {
    wsl -d Ubuntu -- env "FLYDRONES_PX4_RUN_DIR=$runDir" bash "$linuxRoot/tools/stop_px4_swarm_wsl.sh"
}
