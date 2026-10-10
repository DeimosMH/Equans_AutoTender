#!/usr/bin/env python3
"""AutoTender CLI: calculator + prediction, or LoRA dataset preparation.
External training is configured separately after the provider contract is available.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
PRED = BASE/'_3_Prediction'
sys.path.insert(0, str(PRED))
from dataset import TASKS
from jobs import JobStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    calc = commands.add_parser('calculate', help='Run calculator and bid scenarios')
    calc.add_argument('--positions', type=Path, default=BASE/'_2_Calculator/input/example_lv_positions.csv')
    calc.add_argument('--output', type=Path, default=BASE/'_2_Calculator/output/calc.json')
    calc.add_argument('--factors', type=Path, help='JSON productivity factor overrides')
    prepare = commands.add_parser('prepare', help='Prepare tracked datasets; no remote submission')
    prepare.add_argument('--task', choices=TASKS, required=True)
    prepare.add_argument('--base-model', required=True)
    prepare.add_argument('--url', action='append', default=[])
    prepare.add_argument('--uploads', type=Path, default=BASE/'web_ui/uploads/lora_data')
    prepare.add_argument('--jobs', type=Path, default=BASE/'_3_Prediction/output/cli_jobs')
    prepare.add_argument('--exclude-existing', action='store_true')
    args = parser.parse_args()
    if args.command == 'calculate':
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, AUTOTENDER_CALC_OUT=str(output))
        if args.factors:
            env['AUTOTENDER_FACTORS'] = json.dumps(json.loads(args.factors.read_text()))
        for script in ('step1_material.py','step2_labour.py','step3_combine.py','step4_project.py'):
            command = [sys.executable, str(BASE/'_2_Calculator'/script)]
            if script == 'step1_material.py':
                command.append(str(args.positions.resolve()))
            subprocess.run(command, env=env, check=True)
        subprocess.run([sys.executable,str(PRED/'predict.py'),'--calc',str(output)],check=True)
        print(f'Calculation written to {output}')
        return 0
    store = JobStore(args.jobs, PRED/'data', BASE.parent/'materials')
    job = store.start(args.task,args.base_model,' '.join(args.url),args.uploads,
                      include_existing=not args.exclude_existing)
    previous = None
    while True:
        job = store.get(job['id'])
        if job['status'] != previous:
            print(f"{job['id']}: {job['status']}", flush=True)
            previous = job['status']
        if job['status'] not in ('queued','collecting','preparing'):
            print(json.dumps(job,indent=2))
            return 1 if job['status'] == 'failed' else 0
        time.sleep(.2)


if __name__ == '__main__':
    sys.exit(main())
