#!/usr/bin/env python3
"""Create the final tables, trajectory figure, and interactive replay."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from flydrones.benchmark.provenance import verify_sealed_manifest
from flydrones.benchmark.report import path_length, summarize_controller
from flydrones.benchmark.runner import verify_freeze_manifest


CONTROLLERS = ('fly_raw', 'fly_guided', 'ego')
COLOURS = {'fly_raw': '#7b2cbf', 'fly_guided': '#f77f00', 'ego': '#0077b6'}


def load_results(formal_dir: Path, freeze_path: Path):
    freeze = verify_freeze_manifest(freeze_path, ROOT)
    seeds = json.loads((formal_dir / 'seed_manifest.json').read_text(encoding='utf-8'))
    verify_sealed_manifest(seeds)
    episodes = []
    worlds = {}
    for item in seeds['worlds']:
        worlds[item['seed']] = json.loads((ROOT / item['world_json']).read_text(encoding='utf-8'))
        for controller in CONTROLLERS:
            path = formal_dir / 'episodes' / str(item['seed']) / controller / 'result.json'
            if not path.is_file():
                raise ValueError(f'missing formal result: {path}')
            result = json.loads(path.read_text(encoding='utf-8'))
            if result.get('freeze_manifest_sha256') != freeze['manifest_sha256']:
                raise ValueError(f'wrong freeze on result: {path}')
            episodes.append(result)
    if len(episodes) != 60:
        raise ValueError(f'expected 60 episodes, found {len(episodes)}')
    return freeze, seeds, worlds, episodes


def write_csv(path: Path, episodes: list[dict]):
    fields = [
        'seed', 'family', 'controller', 'status', 'elapsed_sim_s', 'wall_s',
        'minimum_clearance_m', 'contact_truth', 'envelope_collision',
        'decision_count', 'decision_wall_mean_s', 'path_length_m',
    ]
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in episodes:
            latency = [decision['decision_wall_s'] for decision in result['decisions']]
            writer.writerow({
                'seed': result['seed'], 'family': result['family'],
                'controller': result['controller'], 'status': result['status'],
                'elapsed_sim_s': result['elapsed_sim_s'], 'wall_s': result['wall_s'],
                'minimum_clearance_m': result['minimum_clearance_m'],
                'contact_truth': result['contact_truth'],
                'envelope_collision': result['envelope_collision'],
                'decision_count': len(result['decisions']),
                'decision_wall_mean_s': float(np.mean(latency)) if latency else None,
                'path_length_m': path_length(result['path']),
            })


def draw_world(ax, world: dict):
    for box in world['boxes']:
        lo, hi = np.asarray(box['lo']), np.asarray(box['hi'])
        ax.add_patch(Rectangle(lo[:2], *(hi - lo)[:2], color='#777777', alpha=.45))
    for cylinder in world['cylinders']:
        ax.add_patch(Circle(cylinder['center'], cylinder['radius'], color='#6a994e', alpha=.55))
    for obstacle in world.get('dynamic', []):
        center, size = np.asarray(obstacle['center']), np.asarray(obstacle['size'])
        ax.add_patch(Rectangle(center[:2] - size[:2] / 2, *size[:2], color='#d62828', alpha=.5))
    ax.scatter(*world['start'][:2], marker='o', color='black', s=10)
    ax.scatter(*world['goal'][:2], marker='*', color='#2a9d8f', s=30)
    lo, hi = world['bounds']
    ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_aspect('equal')


def write_figure(path: Path, seed_manifest: dict, worlds: dict, episodes: list[dict]):
    by_key = {(episode['seed'], episode['controller']): episode for episode in episodes}
    figure, axes = plt.subplots(4, 5, figsize=(17, 10), constrained_layout=True)
    for ax, item in zip(axes.flat, seed_manifest['worlds']):
        world = worlds[item['seed']]
        draw_world(ax, world)
        for controller in CONTROLLERS:
            result = by_key[(item['seed'], controller)]
            points = np.asarray([sample['position'] for sample in result['path']])
            if len(points):
                ax.plot(points[:, 0], points[:, 1], color=COLOURS[controller], linewidth=1,
                        label=f'{controller}: {result["status"]}')
        ax.set_title(f'{item["family"]}\n{item["seed"]}', fontsize=8)
        ax.tick_params(labelsize=6)
    handles = [plt.Line2D([0], [0], color=COLOURS[name], label=name) for name in CONTROLLERS]
    figure.legend(handles=handles, loc='outside lower center', ncol=3)
    figure.savefig(path, dpi=180)
    plt.close(figure)


def write_replay(path: Path, worlds: dict, episodes: list[dict]):
    payload = {
        f'{episode["seed"]}:{episode["controller"]}': {
            'world': worlds[episode['seed']],
            'status': episode['status'],
            'path': episode['path'],
        }
        for episode in episodes
    }
    data = json.dumps(payload, separators=(',', ':')).replace('</', '<\\/')
    html = f'''<!doctype html><meta charset="utf-8"><title>Fly vs EGO trajectory replay</title>
<style>body{{font:14px system-ui;margin:20px;background:#f5f3ef;color:#202020}}canvas{{background:white;border:1px solid #aaa;max-width:100%}}button,select,input{{margin:4px;padding:6px}}#meta{{font-weight:600}}</style>
<h1>果蝇连接组 vs EGO-Swarm 轨迹回放</h1><select id="run"></select><button id="play">播放 / 暂停</button><input id="step" type="range" min="0" value="0"><span id="meta"></span><br><canvas id="c" width="960" height="640"></canvas>
<script>const runs={data};const sel=document.querySelector('#run'),slider=document.querySelector('#step'),ctx=document.querySelector('#c').getContext('2d'),meta=document.querySelector('#meta');let timer=null;
Object.keys(runs).forEach(k=>{{let o=document.createElement('option');o.value=k;o.textContent=k+' — '+runs[k].status;sel.appendChild(o)}});
function xy(p,w){{let lo=w.bounds[0],hi=w.bounds[1];return [(p[0]-lo[0])/(hi[0]-lo[0])*920+20,620-(p[1]-lo[1])/(hi[1]-lo[1])*600]}}
function draw(){{let r=runs[sel.value],w=r.world,n=Math.min(+slider.value,r.path.length-1);ctx.clearRect(0,0,960,640);ctx.fillStyle='#7778';w.boxes.forEach(b=>{{let a=xy(b.lo,w),z=xy(b.hi,w);ctx.fillRect(a[0],z[1],z[0]-a[0],a[1]-z[1])}});ctx.fillStyle='#6a994eaa';w.cylinders.forEach(o=>{{let q=xy(o.center,w),rad=o.radius/(w.bounds[1][0]-w.bounds[0][0])*920;ctx.beginPath();ctx.arc(q[0],q[1],rad,0,7);ctx.fill()}});if(r.path.length){{ctx.strokeStyle='#0077b6';ctx.lineWidth=2;ctx.beginPath();r.path.slice(0,n+1).forEach((s,i)=>{{let q=xy(s.position,w);i?ctx.lineTo(...q):ctx.moveTo(...q)}});ctx.stroke();let q=xy(r.path[n].position,w);ctx.fillStyle='#d62828';ctx.beginPath();ctx.arc(q[0],q[1],6,0,7);ctx.fill();meta.textContent=`${{sel.value}} | ${{r.status}} | t=${{((r.path[n].sim_ns-r.path[0].sim_ns)/1e9).toFixed(2)}} s`}}}}
function reset(){{slider.max=Math.max(0,runs[sel.value].path.length-1);slider.value=0;draw()}}sel.onchange=reset;slider.oninput=draw;document.querySelector('#play').onclick=()=>{{if(timer){{clearInterval(timer);timer=null}}else timer=setInterval(()=>{{slider.value=(+slider.value+1)%(+slider.max+1);draw()}},50)}};reset();</script>'''
    path.write_text(html, encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze-manifest', type=Path, default=ROOT / 'results/fly-ego-comparison/freeze/manifest.json')
    parser.add_argument('--formal-dir', type=Path, default=ROOT / 'results/fly-ego-comparison/formal')
    args = parser.parse_args()
    freeze, seeds, worlds, episodes = load_results(args.formal_dir, args.freeze_manifest)
    summaries = {controller: summarize_controller([e for e in episodes if e['controller'] == controller]) for controller in CONTROLLERS}
    summary = {'freeze_manifest_sha256': freeze['manifest_sha256'], 'controllers': summaries}
    (args.formal_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    write_csv(args.formal_dir / 'episodes.csv', episodes)
    write_figure(args.formal_dir / 'trajectory_overview.png', seeds, worlds, episodes)
    write_replay(args.formal_dir / 'replay.html', worlds, episodes)
    lines = ['# 完整果蝇连接组与 EGO-Swarm 正式对照报告', '', f'- 冻结清单：`{freeze["manifest_sha256"]}`', '- 正式测试：20 个冻结后生成的未见世界，每个世界 3 个控制器，共 60 回合。', '- 所有终局均计入汇总，包含碰撞、越界、超时及基础设施/控制器错误。', '', '| 控制器 | 成功 | 碰撞 | 越界 | 超时 | 平均决策墙钟 | 平均最小净空 |', '|---|---:|---:|---:|---:|---:|---:|']
    for controller in CONTROLLERS:
        item, counts = summaries[controller], summaries[controller]['status_counts']
        latency, clearance = item['decision_wall_s']['mean'], item['minimum_clearance_m']['mean']
        latency_text = f'{latency:.4f} s' if latency is not None else 'N/A'
        clearance_text = f'{clearance:.3f} m' if clearance is not None else 'N/A'
        lines.append(f'| {controller} | {counts.get("success",0)}/20 | {counts.get("collision",0)} | {counts.get("out_of_bounds",0)} | {counts.get("timeout",0)} | {latency_text} | {clearance_text} |')
    lines += ['', '## 真实性与限制', '', '- 动力学由 PX4 SITL 与 Gazebo Sim 执行，RGB-D 为 160×120、10 Hz；三方共享速度、加速度、偏航速率、起终点及机体安全包络。', '- 每个控制决策之间仿真停止，随后精确推进 50 个 1 ms 物理步。因此控制器计算延迟被单独记录，不会改变物理时间。', '- 完整果蝇推理由 166,700 个神经元和 25,582,837 条连接执行，明显慢于实时；这项测试不能直接证明真机实时可部署。', '- EGO-Swarm 使用固定上游提交。其 ROS 2 `traj_server` 原始时间戳来自墙钟；报告保留该原始值，并用接收参考时最近的仿真观测时刻做新鲜度校验。', '- 这是软件在环仿真结果，未覆盖真实传感器噪声、气动失配、机载算力和通信故障。']
    (args.formal_dir / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
