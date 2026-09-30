"""Create a standalone trajectory replay from a preserved relay event log."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HTML = """<!doctype html>
<html lang="zh"><meta charset="utf-8"><title>PX4/Gazebo VIO 轨迹回放</title>
<style>
body{font:15px system-ui,sans-serif;background:#101923;color:#e8eef5;max-width:1000px;margin:24px auto;padding:0 16px}
canvas{width:100%;background:#172330;border:1px solid #3d5368;border-radius:8px}
.controls{display:flex;gap:14px;align-items:center;margin:12px 0}input{flex:1}button{padding:8px 18px}
small{color:#a9bdcf}span{font-variant-numeric:tabular-nums}
</style>
<h1>PX4/Gazebo 轨迹回放：<span id="name"></span></h1>
<p>实心点为 Gazebo 原始位置；0 号机的空心圈为注入后送给 PX4 的里程计位置。树干为棕色圆圈。轨迹为仿真真值，不代表真实相机 VIO 精度。</p>
<canvas id="scene" width="960" height="680"></canvas>
<div class="controls"><button id="play">播放</button><input id="time" type="range" min="0" step="0.05"><span id="clock">0.0 s</span></div>
<small>单机或五机 PX4 SITL；仅显示平面位置。原始数据见同目录 vio-relay.jsonl。</small>
<script>
const data=__DATA__;
document.getElementById('name').textContent=data.name;
const canvas=document.getElementById('scene'),ctx=canvas.getContext('2d');
const slider=document.getElementById('time'),clock=document.getElementById('clock'),play=document.getElementById('play');
slider.max=data.duration.toFixed(2);
const colors=['#50c5ff','#f5c45b','#8ae8a0','#e98de6','#ff886f'];
function xy(x,y){return [70+(x+1)*98,620-(y+6)*47]}
function draw(){
 const t=Number(slider.value);clock.textContent=t.toFixed(1)+' s';ctx.clearRect(0,0,960,680);
 ctx.strokeStyle='#2d4052';ctx.lineWidth=1;
 for(let x=0;x<=7;x++){let p=xy(x,-6);ctx.beginPath();ctx.moveTo(p[0],35);ctx.lineTo(p[0],630);ctx.stroke();ctx.fillStyle='#8098ac';ctx.fillText(x+' m',p[0]-8,653)}
 for(let y=-6;y<=6;y+=2){let p=xy(-1,y);ctx.beginPath();ctx.moveTo(65,p[1]);ctx.lineTo(865,p[1]);ctx.stroke();ctx.fillStyle='#8098ac';ctx.fillText(y+' m',10,p[1]+4)}
 for(let i=0;i<5;i++){let p=xy(2.5,(i-2)*2+0.05);ctx.fillStyle='#926b42';ctx.beginPath();ctx.arc(...p,11,0,2*Math.PI);ctx.fill()}
 data.tracks.forEach((track,i)=>{let shown=track.filter(p=>p[0]<=t);if(!shown.length)return;
  ctx.strokeStyle=colors[i];ctx.lineWidth=2;ctx.beginPath();shown.forEach((p,j)=>{let q=xy(p[1],p[2]);j?ctx.lineTo(...q):ctx.moveTo(...q)});ctx.stroke();
  let q=xy(shown.at(-1)[1],shown.at(-1)[2]);ctx.fillStyle=colors[i];ctx.beginPath();ctx.arc(...q,7,0,2*Math.PI);ctx.fill();
  ctx.fillStyle='#e8eef5';ctx.fillText('机 '+i,q[0]+10,q[1]-10);
 });
 let fault=data.injected.filter(p=>p[0]<=t);if(fault.length){let q=xy(fault.at(-1)[1],fault.at(-1)[2]);ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(...q,11,0,2*Math.PI);ctx.stroke()}
}
slider.addEventListener('input',draw);let timer=null;play.onclick=()=>{if(timer){clearInterval(timer);timer=null;play.textContent='播放';return}
 play.textContent='暂停';timer=setInterval(()=>{slider.value=Math.min(data.duration,Number(slider.value)+0.15);draw();if(Number(slider.value)>=data.duration){clearInterval(timer);timer=null;play.textContent='播放'}},100)};
draw();
</script></html>"""


def generate(directory: Path) -> Path:
    log = directory / "vio-relay.jsonl"
    tracks: dict[int, list[list[float]]] = {index: [] for index in range(5)}
    injected: list[list[float]] = []
    first_time = None
    last_bucket: dict[int, int] = {}
    last_injected_bucket = -1
    for line in log.open(encoding="utf-8"):
        event = json.loads(line)
        if event.get("event") == "ingress" and "raw_position_m" in event:
            now = event["received_at"]
            first_time = now if first_time is None else first_time
            vehicle_id = int(event["model"].rsplit("_", 1)[-1])
            bucket = int((now - first_time) * 10)
            if bucket != last_bucket.get(vehicle_id):
                position = event["raw_position_m"]
                tracks[vehicle_id].append([round(now - first_time, 3), position[0], position[1]])
                last_bucket[vehicle_id] = bucket
        elif event.get("event") == "publish" and event.get("model") == "x500_depth_fly_0" and event.get("active"):
            if first_time is None or "published_position_m" not in event:
                continue
            now = event["published_at"]
            bucket = int((now - first_time) * 10)
            if bucket != last_injected_bucket:
                position = event["published_position_m"]
                injected.append([round(now - first_time, 3), position[0], position[1]])
                last_injected_bucket = bucket
    duration = max((track[-1][0] for track in tracks.values() if track), default=0.0)
    payload = {"name": directory.name, "tracks": [tracks[index] for index in range(5)],
               "injected": injected, "duration": duration}
    target = directory / "trajectory-replay.html"
    target.write_text(HTML.replace("__DATA__", json.dumps(payload, separators=(",", ":"))), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trial", type=Path, nargs="+")
    args = parser.parse_args()
    for trial in args.trial:
        print(generate(trial))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
