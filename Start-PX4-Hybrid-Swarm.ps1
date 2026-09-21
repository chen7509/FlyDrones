param(
    [switch]$ResolveOnly
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$drive = $repoRoot.Substring(0, 1).ToLowerInvariant()
$pathWithinDrive = $repoRoot.Substring(3).Replace('\', '/')
$linuxRoot = "/mnt/$drive/$pathWithinDrive"
if ($ResolveOnly) {
    Write-Output $linuxRoot
    exit 0
}

$completedWindows = @()
for ($run = 1; $run -le 5; $run++) {
    $runDir = "/tmp/flydrones-hybrid-$run"
    $peerBasePort = 18000 + $run * 10
    $outputRelative = "results/px4-hybrid-repeatability/run-$run"
    $outputLinux = "$linuxRoot/$outputRelative"
    $outputWindows = Join-Path $repoRoot $outputRelative
    try {
        wsl -d Ubuntu -- env "FLYDRONES_PX4_RUN_DIR=$runDir" bash "$linuxRoot/tools/launch_px4_depth_swarm_wsl.sh"
        if ($LASTEXITCODE -ne 0) { throw "PX4 startup failed for run $run" }

        wsl -d Ubuntu -- env "PYTHONPATH=$linuxRoot/src" python3 "$linuxRoot/tools/run_distributed_px4_swarm.py" `
            --model "$linuxRoot/results/autonomous-forest-ppo-v1/autonomous-policy-numpy.npz" `
            --peer-base-port $peerBasePort `
            --output $outputLinux
        if ($LASTEXITCODE -ne 0) { throw "PX4 acceptance failed for run $run" }
        $completedWindows += $outputWindows
    }
    finally {
        wsl -d Ubuntu -- env "FLYDRONES_PX4_RUN_DIR=$runDir" bash "$linuxRoot/tools/stop_px4_swarm_wsl.sh"
    }
}

$env:PYTHONPATH = (Resolve-Path (Join-Path $repoRoot 'src')).Path
python (Join-Path $repoRoot 'tools/report_hybrid_px4_repeatability.py') `
    --required 5 `
    --output (Join-Path $repoRoot 'results/px4-hybrid-repeatability') `
    @completedWindows
if ($LASTEXITCODE -ne 0) { throw 'Five-run repeatability evaluation failed.' }
