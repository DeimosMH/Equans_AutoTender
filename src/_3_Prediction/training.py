"""Provider-neutral training handoff. Chat completion compatibility is not LoRA capability."""
import json
from pathlib import Path

def write_training_request(output_dir, manifest):
    request = {'schema_version':1, 'operation':'lora_training', 'task':manifest['task'],
        'base_model':manifest['base_model'], 'dataset_manifest':'manifest.json',
        'files':{'train':'train.jsonl', 'validation':'validation.jsonl', 'test':'test.jsonl'},
        'dataset_hashes':manifest['hashes'], 'submission_status':'not_submitted',
        'endpoint_expectation':'User will provide an endpoint supporting LoRA job creation; exact contract pending.',
        'optional_local_training_command':'python train_lora.py --model <actual-HF-model-id> --train train.jsonl --validation validation.jsonl --output <new-adapter-dir>',
        'provider_configuration':{'endpoint_env':'AUTOTENDER_TRAINING_ENDPOINT',
                                  'api_key_env':'AUTOTENDER_TRAINING_API_KEY'},
        'requirements':['Provider must explicitly support training this base model with LoRA.',
                        'Keep test data held out; evaluate and calibrate before registering any adapter.',
                        'Register adapter only after verified training completion and evaluation.'],
        'adapter_registration_contract':{'adapter_id':'provider adapter/model ID', 'base_model':manifest['base_model'],
             'task':manifest['task'], 'dataset_hash':'manifest digest', 'evaluation_report':'required artifact',
             'status':'evaluated'}}
    path = Path(output_dir)/'training_request.json'
    path.write_text(json.dumps(request, indent=2)+'\n')
    return request
