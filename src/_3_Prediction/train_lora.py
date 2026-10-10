#!/usr/bin/env python3
"""Optional local causal-LM LoRA training. Does not register or activate adapters.

Install requirements-training.txt in a separate GPU environment. Pass an actual
Hugging Face causal model identifier, not the UI's friendly base-model label.
"""
import argparse
import hashlib
import json
from pathlib import Path


def read_examples(path):
    rows = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        messages = row.get('messages')
        if not isinstance(messages, list) or len(messages) < 2:
            raise ValueError(f'{path}:{number}: messages required')
        if messages[-1].get('role') != 'assistant':
            raise ValueError(f'{path}:{number}: final assistant answer required')
        if any(m.get('role') not in ('system', 'user', 'assistant') or
               not isinstance(m.get('content'), str) for m in messages):
            raise ValueError(f'{path}:{number}: invalid message')
        rows.append(messages)
    if not rows:
        raise ValueError(f'{path}: empty dataset')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--train', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-length', type=int, default=2048)
    parser.add_argument('--epochs', type=float, default=3)
    parser.add_argument('--rank', type=int, default=16)
    parser.add_argument('--learning-rate', type=float, default=0.0002)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if args.max_length < 32 or args.rank < 1 or args.epochs <= 0 or args.learning_rate <= 0:
        parser.error('invalid training configuration')
    train, validation = read_examples(args.train), read_examples(args.validation)
    fingerprints = lambda rows: {json.dumps(r, sort_keys=True) for r in rows}
    if fingerprints(train) & fingerprints(validation):
        raise ValueError('identical examples cross train and validation; use dataset.py grouped splits')
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('output directory must be empty to preserve previous adapters')
    if args.check_only:
        print(json.dumps({'train': len(train), 'validation': len(validation), 'model': args.model}))
        return
    import torch
    from torch.utils.data import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, set_seed
    from peft import LoraConfig, get_peft_model
    set_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=False)
    if not tokenizer.chat_template:
        raise ValueError('model tokenizer must define a chat template')
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(args.model, trust_remote_code=False)
    model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=2 * args.rank,
                           lora_dropout=0.05, target_modules='all-linear',
                           task_type='CAUSAL_LM', bias='none'))
    model.config.use_cache = False

    class Examples(Dataset):
        def __init__(self, rows):
            self.items = []
            for messages in rows:
                prefix = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True)
                tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False)
                # Prefix alignment is necessary to mask prompt tokens reliably.
                if tokens[:len(prefix)] != prefix:
                    raise ValueError('chat template prefix mismatch; model requires a custom data collator')
                tokens = tokens[:args.max_length]
                if len(tokens) <= len(prefix):
                    raise ValueError('completion truncated entirely; increase --max-length')
                labels = [-100] * len(prefix) + tokens[len(prefix):]
                self.items.append({'input_ids': tokens, 'labels': labels})
        def __len__(self):
            return len(self.items)
        def __getitem__(self, index):
            return self.items[index]

    def collate(rows):
        width = max(len(row['input_ids']) for row in rows)
        return {'input_ids': torch.tensor([r['input_ids'] + [tokenizer.pad_token_id] * (width-len(r['input_ids'])) for r in rows]),
                'attention_mask': torch.tensor([[1] * len(r['input_ids']) + [0] * (width-len(r['input_ids'])) for r in rows]),
                'labels': torch.tensor([r['labels'] + [-100] * (width-len(r['labels'])) for r in rows])}

    trainer = Trainer(model=model, args=TrainingArguments(output_dir=str(args.output / 'checkpoints'),
                      num_train_epochs=args.epochs, learning_rate=args.learning_rate,
                      per_device_train_batch_size=1, per_device_eval_batch_size=1,
                      gradient_accumulation_steps=8, eval_strategy='epoch', save_strategy='epoch',
                      seed=args.seed, report_to='none'), train_dataset=Examples(train),
                      eval_dataset=Examples(validation), data_collator=collate)
    trainer.train()
    metrics = trainer.evaluate()
    model.save_pretrained(args.output)
    tokenizer.save_pretrained(args.output)
    metadata = {'status': 'trained_unvalidated', 'base_model_id': args.model,
                'train_sha256': hashlib.sha256(args.train.read_bytes()).hexdigest(),
                'validation_sha256': hashlib.sha256(args.validation.read_bytes()).hexdigest(),
                'training_examples': len(train), 'validation_examples': len(validation),
                'metrics': metrics, 'seed': args.seed,
                'promotion': 'requires task evaluation; loss does not establish calibrated win probabilities'}
    (args.output / 'training_metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata))


if __name__ == '__main__':
    main()
