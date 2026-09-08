#!/usr/bin/env python3
"""Audit saved model inputs for approval-plane fields and the known fixture key."""
import argparse
import hashlib
import json
from pathlib import Path

FORBIDDEN = {'nonce', 'signature', 'approval_request', 'approval_key', 'signing_key'}
FIXTURE_KEY = 'docker-fixture-only-secret'


def inspect(value, path='$'):
    findings = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN:
                findings.append({'path':path+'.'+key, 'kind':'approval_field'})
            findings.extend(inspect(child, path+'.'+key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(inspect(child, path+f'[{index}]'))
    elif isinstance(value, str):
        if FIXTURE_KEY in value:
            findings.append({'path':path, 'kind':'known_fixture_key_literal'})
        # Tool message content serializes nested JSON. Decode objects/lists only.
        if value.lstrip().startswith(('{', '[')):
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                pass
            else:
                findings.extend(inspect(decoded, path+'.decoded'))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows, sources = [], {}
    for path in args.inputs:
        raw = path.read_bytes()
        report = json.loads(raw)
        if report.get('status') not in {'completed', 'runtime_error'}:
            raise ValueError('terminal report required')
        sources[str(path)] = hashlib.sha256(raw).hexdigest()
        for trial in report['trials']:
            inputs = trial.get('public_inputs')
            findings = inspect(inputs) if isinstance(inputs, list) else None
            rows.append({'input':str(path), 'case_id':trial.get('case_id'), 'condition':trial.get('condition'),
                'repetition':trial.get('repetition'), 'started':trial.get('started'),
                'saved_input_count':len(inputs) if isinstance(inputs,list) else None,
                'findings':findings, 'scope':'saved prepared model inputs only'})
    result = {'protocol':'sabakan-approval-history-audit-v1','input_sha256':sources,
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'rows':rows,
        'limitations':['Does not recover absent history, approval objects or exact transient nonce/signature values.',
                       'Checks structured field names and the known fixture key literal; encoded, paraphrased or unrelated leakage is outside this audit.',
                       'Zero matching fields is not a general confidentiality guarantee.']}
    with args.output.open('x') as output:
        json.dump(result,output,indent=2)
        output.write('\n')
    print('trials',len(rows),'findings',sum(len(r['findings'] or []) for r in rows))
    return 1 if any(r['findings'] for r in rows) else 0


if __name__ == '__main__':
    raise SystemExit(main())
