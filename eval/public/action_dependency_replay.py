"""Dependency trace consistency, not authentication or independent reproduction."""

import argparse
from pathlib import Path

from eval.public.action_dependency_plan import make_corpus, observation_plan
from eval.public.action_dependency_observe import observe_case, score_observations
from eval.public.action_dependency_scoring import score_case
from eval.public.action_formation_replay import _recompute
from eval.public.bundle import _canonical

HARNESS_FILES = ('action_timing_run.py', 'action_cli.py', 'action_timing.py', 'action_sink.py',
                 'action_formation.py', 'action_dependency_run.py', 'action_implicit_plan.py',
                 'action_dependency_plan.py', 'action_dependency_scoring.py', 'action_dependency_observe.py',
                 'action_dependency_replay.py', 'action_formation_scoring.py', 'action_formation_observe.py',
                 'action_formation_timing.py', 'action_trigger_timing.py', 'action_formation_replay.py',
                 'action_formation_ollama.py', 'action_formation_schema.py')


def recompute(output):
    return _recompute(output, corpus_factory=make_corpus, plan_factory=observation_plan,
                      observer=observe_case, state_scorer=score_case, timing_scorer=score_observations,
                      harness_files=HARNESS_FILES, schema_prefix='m12-dependency-formation',
                      execution_version='v1', session_id='dependency-formation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(_canonical(recompute(parser.parse_args().output)).decode(), end='')
