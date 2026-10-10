"""Record evidence-backed productivity factors; export supervision without changing prices."""
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location('recursive_core', Path(__file__).with_name('core.py'))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)


def record_measurement(folder, uploads, params, payload):
    target = payload.get('target')
    if not isinstance(target, dict) or set(target) - set(params['productivity_factors']):
        raise ValueError('Only configured productivity factors can be recorded')
    reference = payload.get('measurement_reference')
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError('A measurement evidence reference is required')
    if payload.get('verified') is not True:
        raise ValueError('Measurement must be verified before exporting productivity supervision')
    record = {'project_id':Path(folder).name, 'input':payload.get('input'),
              'target':target, 'measurement_reference':reference.strip()[:4000]}
    core.dataset.validate_record(record,'productivity_factors')
    root, uploads = Path(folder)/'feedback', Path(uploads)
    with core._lock(root):
        old = core._read(root,'productivity.json')
        core._atomic(root/'productivity.json',record)
        with core._lock(uploads):
            core._atomic(uploads/f'productivity_factors_feedback_{Path(folder).name}.jsonl',
                         core._canonical(record)+'\n',raw=True)
        if old != record:
            core._audit(root,'productivity_measured',record)
    return {'status':'exported', 'record_count':1, 'task':'productivity_factors',
            'note':'Measurements are training evidence; active calculator factors are unchanged.'}
