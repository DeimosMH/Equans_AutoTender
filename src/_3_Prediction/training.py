"""Provider-neutral training handoff. Chat completion compatibility is not LoRA capability."""
import json
from pathlib import Path

def write_training_request(output_dir, manifest):
    request = {'schema_version':1, 'operation':'lora_training', 'task':manifest['task'],
        'base_model':manifest['base_model'], 'dataset_manifest':'manifest.json',
        'files':{'train':'train.jsonl', 'validation':'validation.jsonl', 'test':'test.jsonl'},
        'dataset_hashes':manifest['hashes'], 'submission_status':'not_submitted',
        'dataset_status':manifest['status'], 'blockers':manifest['blockers'],
        'method':{'type':'lora', 'proposed_parameters':{'rank':16, 'alpha':32,
            'dropout':0.05, 'epochs':3, 'learning_rate':0.0002},
            'status':'Provider must validate architecture, target modules and supported parameters.'},
        'evaluation':{'test_file':'test.jsonl', 'upload_test_for_training':False,
            'required':['held-out task quality', 'comparison with current baseline',
                        'chronological evaluation and calibration for win prediction']},
        'endpoint_expectation':'User will provide an endpoint supporting LoRA job creation; exact contract pending.',
        'execution':{'location':'user_managed_cloud_docker', 'runtime_status':'not_connected',
            'training_contract_required':True,
            'inference_compatibility_does_not_imply_training_support':True},
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
