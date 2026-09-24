$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$drive = $repoRoot.Substring(0, 1).ToLowerInvariant()
$pathWithinDrive = $repoRoot.Substring(3).Replace('\', '/')
$linuxRoot = "/mnt/$drive/$pathWithinDrive"
$runDir = '/tmp/flydrones-px4-vio-fallback'

try {
    wsl -d Ubuntu -- env "FLYDRONES_PX4_RUN_DIR=$runDir" bash "$linuxRoot/tools/launch_px4_depth_swarm_wsl.sh"
    if ($LASTEXITCODE -ne 0) { throw 'PX4/Gazebo VIO-fallback startup failed.' }

    wsl -d Ubuntu -- env "PYTHONPATH=$linuxRoot/src" python3 "$linuxRoot/tools/run_distributed_px4_swarm.py" `
        --model "$linuxRoot/results/autonomous-forest-ppo-v1/autonomous-policy-numpy.npz" `
        --mission-timeout 70 `
        --process-timeout 150 `
        --peer-base-port 16970 `
        --output "$linuxRoot/results/px4-vio-fallback" `
        --gps-failure-vehicle 0 `
        --gps-failure-at 5 `
        --gps-failure-mode fusion-off `
        --external-vision-fusion `
        --expect-gps-vio-fallback
    if ($LASTEXITCODE -ne 0) { throw 'GNSS-loss VIO-fallback acceptance failed.' }
}
finally {
    wsl -d Ubuntu -- env "FLYDRONES_PX4_RUN_DIR=$runDir" bash "$linuxRoot/tools/stop_px4_swarm_wsl.sh"
}
