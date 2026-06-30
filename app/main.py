from __future__ import annotations
import argparse
import json
import logging
from pathlib import Path
from typing import Any
from app.workflow import run_workflow

def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(name)s | %(message)s')

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Multi-agent software development workflow')
    parser.add_argument('--task', default='Build a small CLI TODO application with persistence and unit tests.', help='User task to execute through the multi-agent workflow.')
    parser.add_argument('--workspace', default='.', help='Workspace directory where artifacts and tests will run.')
    parser.add_argument('--models-config', default='configs/models_example.yaml', help='Path to the role/model mapping file.')
    parser.add_argument('--system-config', default='configs/system.yaml', help='Path to the system configuration file.')
    return parser.parse_args()

def main() -> None:
    configure_logging()
    args = parse_args()
    logger = logging.getLogger(__name__)
    logger.info('Loaded model configuration from %s', args.models_config)
    final_state: dict[str, Any] = run_workflow(user_task=args.task, workspace=Path(args.workspace).resolve(), models_config_path=args.models_config, system_config_path=args.system_config)
    print('\n=== Final Status ===')
    print(final_state.get('final_status'))
    print('\n=== Summary ===')
    print(final_state.get('implementation_summary'))
    print('\n=== Test Results ===')
    print(json.dumps(final_state.get('test_results', {}), indent=2))
    print('\n=== Final Output Path ===')
    print(final_state.get('final_output_path'))
if __name__ == '__main__':
    main()