import argparse
import sys
from storage import StorageHandler
from manager import TaskManager, TaskNotFoundError

def main():
    parser = argparse.ArgumentParser(description='Simple CLI TODO Application')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    add_parser = subparsers.add_parser('add', help='Add a new task')
    add_parser.add_argument('description', type=str, help='Task description')
    subparsers.add_parser('list', help='List all tasks')
    done_parser = subparsers.add_parser('done', help='Mark a task as completed')
    done_parser.add_argument('id', type=int, help='Task ID')
    del_parser = subparsers.add_parser('del', help='Delete a task')
    del_parser.add_argument('id', type=int, help='Task ID')
    subparsers.add_parser('clear', help='Clear all completed tasks')
    args = parser.parse_args()
    storage = StorageHandler()
    manager = TaskManager(storage)
    try:
        if args.command == 'add':
            task = manager.add_task(args.description)
            print(f'Added task {task.id}: {task.description}')
        elif args.command == 'list':
            tasks = manager.list_tasks()
            if not tasks:
                print('No tasks found.')
            else:
                print(f"{'ID':<5} {'Status':<12} {'Description'}")
                print('-' * 30)
                for t in tasks:
                    status = 'Done' if t.completed else 'Pending'
                    print(f'{t.id:<5} {status:<12} {t.description}')
        elif args.command == 'done':
            manager.mark_complete(args.id)
            print(f'Task {args.id} marked as completed.')
        elif args.command == 'del':
            manager.delete_task(args.id)
            print(f'Task {args.id} deleted.')
        elif args.command == 'clear':
            manager.clear_completed()
            print('All completed tasks cleared.')
        else:
            parser.print_help()
    except TaskNotFoundError as e:
        print(f'Error: {e}')
        sys.exit(1)
    except ValueError as e:
        print(f'Error: {e}')
        sys.exit(1)
    except Exception as e:
        print(f'An unexpected error occurred: {e}')
        sys.exit(1)
if __name__ == '__main__':
    main()