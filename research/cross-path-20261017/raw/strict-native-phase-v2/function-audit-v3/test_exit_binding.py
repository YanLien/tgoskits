#!/usr/bin/env python3
"""Same-run receipt binding tests using the actual failed AB1 receipt group."""
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
HANDOFF = HERE.parents[2]/'raw/strict-native-phase-v2/AB1-root-final-handoff-v1.json'
HANDOFF_SHA = '30d2613204648b7ebd89a202ee642b725678c94c056dada23e58de34b88cdd91'
MODULE = None
OUTPUT = None
OBSERVATIONS = []


def encoded(document):
    return (json.dumps(document,sort_keys=True,indent=2)+'\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identity_only(module, documents, handoff):
    if hasattr(module,'validate_run_identity'):
        return module.validate_run_identity(documents,handoff)
    # The reviewed v2 checks identity only in these two original expressions.
    # Execute them without its unrelated zero-exit/release preconditions, so the
    # real failed receipt group can expose the missing same-run rule directly.
    raw = Path(module.__file__).read_bytes()
    if sha(raw) != '1e4f19515aa9bc285e1201a85378a166f7b7a7805067ab4b4f6032fa1ad0a22b':
        raise AssertionError('legacy identity slice only supports exact reviewed v2')
    function = next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name == 'validate_exit')
    nodes = []
    for node in function.body:
        constants = {n.value for n in ast.walk(node) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
        if 'Popen.wait' in constants or 'run_result_sha256' in constants:
            nodes.append(node)
    if len(nodes) != 2:
        raise AssertionError('reviewed v2 identity expressions changed')
    namespace = dict(module.__dict__,documents=documents,handoff=handoff,
                     run=documents['run_result'],wait=documents['root_wait'])
    exec(compile(ast.Module(body=nodes,type_ignores=[]),module.__file__,'exec'),namespace)
    return dict(scope='original v2 identity expressions only')


def field_changes(before, after, path=''):
    changes = []
    if isinstance(before,dict) and isinstance(after,dict):
        for key in sorted(before.keys()|after.keys()):
            changes.extend(field_changes(before.get(key),after.get(key),path+'/'+key))
    elif before != after:
        changes.append(dict(field=path,original=before,mutated=after))
    return changes


class ReceiptBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = HANDOFF.read_bytes()
        if sha(raw) != HANDOFF_SHA:
            raise AssertionError('actual final handoff changed')
        cls.handoff = json.loads(raw)
        cls.documents = {}
        for label in ('run_result','root_wait','root_launch','root_tool_completion',
                      'actual_command','approval','frozen_inputs','freeze_manifest'):
            cls.documents[label] = json.loads(MODULE.read_bound(cls.handoff['files'][label]))
        if [cls.documents['run_result']['xtask_wait_exit'],
            cls.documents['root_wait']['driver_wait_exit'],
            cls.documents['root_tool_completion']['actual_unified_exec_exit']] != [1,1,1]:
            raise AssertionError('fixture must remain the actual failed run')

    def materialize(self, name, documents, detach=None):
        """Retain actual receipt mutations and maintain their existing SHA edges."""
        directory = OUTPUT/name
        directory.mkdir()
        handoff = copy.deepcopy(self.handoff)
        def save(label):
            if documents[label] != self.documents[label]:
                raw = encoded(documents[label])
                path = directory/(label+'.json')
                path.write_bytes(raw)
                handoff['files'][label] = dict(path=str(path),bytes=len(raw),sha256=sha(raw))
        for label in ('run_result','actual_command','approval','root_launch'):
            save(label)
        documents['root_wait']['run_result_sha256'] = handoff['files']['run_result']['sha256']
        if detach != 'launch':
            documents['root_wait']['launch_sha256'] = handoff['files']['root_launch']['sha256']
        save('root_wait')
        if 'root_tool_completion' in documents:
            if detach != 'completion':
                documents['root_tool_completion']['driver_Popen_wait_receipt_sha256'] = handoff['files']['root_wait']['sha256']
            save('root_tool_completion')
        else:
            del handoff['files']['root_tool_completion']
        raw = encoded(handoff)
        (directory/'handoff.json').write_bytes(raw)
        # Consume the exact saved test bytes through the same bound reader.
        bound = {label:json.loads(MODULE.read_bound(handoff['files'][label]))
                 for label in documents}
        return bound,handoff,dict(path=str(directory/'handoff.json'),bytes=len(raw),sha256=sha(raw))

    def test_one_recorded_run_cannot_borrow_other_run_receipts(self):
        baseline = identity_only(MODULE,self.documents,self.handoff)
        self.assertIsInstance(baseline,dict)
        self.assertEqual(self.documents['root_tool_completion']['actual_unified_exec_exit'],1)
        cases = ['foreign-case-pair','foreign-Popen-child','wrong-driver-source',
                 'detached-command-approval','detached-launch','detached-completion',
                 'contradictory-completion-exit','missing-original-completion']
        for name in cases:
            with self.subTest(identity_edge=name):
                documents = copy.deepcopy(self.documents)
                if name == 'foreign-case-pair':
                    documents['run_result']['case_id'] = 'AB0'
                    documents['root_wait']['case_id'] = 'AB0'
                    argv = documents['root_wait']['driver']['argv']
                    argv[argv.index('--run')+1] = 'AB0'
                elif name == 'foreign-Popen-child':
                    child = documents['root_wait']['driver']
                    child['pid'] += 1
                    child['starttime'] = str(int(child['starttime'])+1)
                    documents['root_wait']['driver_pid_from_Popen'] = child['pid']
                elif name == 'wrong-driver-source':
                    for argv in (documents['root_launch']['argv'],documents['root_launch']['driver']['argv'],documents['root_wait']['driver']['argv']):
                        index = argv.index('--source-manifest-sha')+1
                        argv[index] = '1'+argv[index][1:]
                elif name == 'detached-command-approval':
                    value = documents['actual_command']['approval_sha256']
                    documents['actual_command']['approval_sha256'] = '1'+value[1:]
                elif name == 'detached-launch':
                    value = documents['root_wait']['launch_sha256']
                    documents['root_wait']['launch_sha256'] = '1'+value[1:]
                elif name == 'detached-completion':
                    value = documents['root_tool_completion']['driver_Popen_wait_receipt_sha256']
                    documents['root_tool_completion']['driver_Popen_wait_receipt_sha256'] = '1'+value[1:]
                elif name == 'contradictory-completion-exit':
                    documents['root_tool_completion']['actual_unified_exec_exit'] = 2
                elif name == 'missing-original-completion':
                    del documents['root_tool_completion']
                changes = field_changes(self.documents,documents)
                bound,handoff,reference = self.materialize(name,documents,
                    'launch' if name == 'detached-launch' else 'completion' if name == 'detached-completion' else None)
                try:
                    identity_only(MODULE,bound,handoff)
                    rejected,reason = False,None
                except (MODULE.AuditError,KeyError) as error:
                    rejected,reason = True,str(error)
                OBSERVATIONS.append(dict(identity_edge=name,changes=changes,
                    test_handoff=reference,rejected=rejected,reason=reason,
                    scope='receipt identity rule only; actual waits remain nonzero; no successful Popen/Guest/Trace fabricated'))
                self.assertTrue(rejected,'same-run receipt rule accepted '+name)


def main():
    global MODULE,OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auditor',type=Path,default=HERE/'audit.py')
    parser.add_argument('--output-dir',type=Path,required=True)
    args,remaining = parser.parse_known_args()
    OUTPUT = args.output_dir.resolve()
    if not OUTPUT.is_relative_to(HERE) or OUTPUT.exists():
        parser.error('fresh child output required')
    OUTPUT.mkdir()
    spec = importlib.util.spec_from_file_location('bound_auditor',args.auditor)
    MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULE)
    program = unittest.main(argv=[__file__]+remaining,exit=False)
    report = dict(auditor=dict(path=str(args.auditor.resolve()),sha256=sha(args.auditor.read_bytes())),
        actual_handoff=dict(path=str(HANDOFF),sha256=HANDOFF_SHA),
        original_receipts=ReceiptBinding.handoff['files'],observations=OBSERVATIONS,
        tests_run=program.result.testsRun,failures=len(program.result.failures),errors=len(program.result.errors),
        baseline_actual_xtask_driver_Root_exit=[1,1,1],
        scope='same-run receipt binding only; no target execution and no success fixture',
        normal_end_to_end_GREEN=False)
    (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return 0 if program.result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
