from __future__ import annotations
import argparse
from todo.repository import TaskRepository
from todo.service import TaskNotFoundError, TodoService

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='CLI TODO application')
    subparsers = parser.add_subparsers(dest='command')
    add_parser = subparsers.add_parser('add', help='Add a task')
    add_parser.add_argument('description')
    subparsers.add_parser('list', help='List tasks')
    done_parser = subparsers.add_parser('done', help='Mark a task as completed')
    done_parser.add_argument('task_id', type=int)
    remove_parser = subparsers.add_parser('remove', help='Delete a task')
    remove_parser.add_argument('task_id', type=int)
    subparsers.add_parser('clear-completed', help='Remove completed tasks')
    return parser

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    service = TodoService(TaskRepository())
    try:
        if args.command == 'add':
            task = service.add_task(args.description)
            print(f'Task {task.id} added: {task.description}')
            return 0
        if args.command == 'list':
            for task in service.list_tasks():
                status = 'x' if task.completed else ' '
                print(f'[{status}] {task.id}: {task.description}')
            return 0
        if args.command == 'done':
            task = service.complete_task(args.task_id)
            print(f'Task {task.id} marked as done.')
            return 0
        if args.command == 'remove':
            service.delete_task(args.task_id)
            print(f'Task {args.task_id} removed.')
            return 0
        if args.command == 'clear-completed':
            removed = service.clear_completed()
            print(f'Removed {removed} completed task(s).')
            return 0
        parser.print_help()
        return 0
    except (ValueError, TaskNotFoundError) as exc:
        print(str(exc))
        return 1
if __name__ == '__main__':
    raise SystemExit(main())