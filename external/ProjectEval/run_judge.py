import argparse
import csv
import datetime
import json
import os
from pathlib import Path

from config import PROJECT_EVAL_DEFAULT_TEST_CASE
from controller import JudgeController
from llm import GPTTest, OllamaTest, GeminiTest, DeepSeekTest
from utils import extract_json_files_from_folder


def _load_group_from_answer_code(answer_code_path: str) -> dict:
    answer_path = Path(answer_code_path).resolve()
    run_dir = answer_path.parent.parent
    summary_dir = run_dir / "summary"
    manifest_path = summary_dir / "run_manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "date": manifest.get("experiment_date") or answer_path.parents[4].name,
        "model": manifest.get("model_label") or answer_path.parents[2].name,
        "mode": manifest.get("mode") or answer_path.parents[1].name,
        "level": int(manifest.get("level") or 0),
        "run_id": manifest.get("run_id") or run_dir.name,
        "answer_code_path": str(answer_path),
        "answer_parameter_path": str((answer_path.parent / "answer_parameter.json").resolve()),
        "answer_information_path": str((answer_path.parent / "answer_information.json").resolve()),
        "answer_startfile_path": str((answer_path.parent / "answer_startfile.json").resolve()),
    }


def _discover_groups(result_output_path: str, date: str) -> list[dict]:
    groups: list[dict] = []
    model_list = os.listdir(os.path.join(result_output_path, date))
    for model in model_list:
        for mode in ("cascade", "direct"):
            dirpath = os.path.join(result_output_path, date, model, mode)
            if not os.path.exists(dirpath):
                print(f"Skip {dirpath}.")
                continue
            run_exports = sorted(Path(dirpath).glob("runs/*/exports/answer_code.json"))
            if run_exports:
                groups.extend(_load_group_from_answer_code(str(path)) for path in run_exports)
                continue
            file_group = extract_json_files_from_folder(dirpath, mode=True)
            for group in file_group:
                try:
                    level = int(str(group).split("_")[3])
                except (IndexError, ValueError):
                    level = 0
                groups.append(
                    {
                        "date": date,
                        "model": model,
                        "mode": mode,
                        "level": level,
                        "run_id": str(group),
                        "answer_code_path": file_group[group]["answer_code_path"],
                        "answer_parameter_path": file_group[group]["answer_parameter_path"],
                        "answer_information_path": file_group[group].get("information"),
                        "answer_startfile_path": file_group[group].get("startfile"),
                    }
                )
    return groups


if __name__ == "__main__":
    current_pid = os.getpid()
    print(f"ProjectEval Main PID: {current_pid}")

    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--dirlist", type=str, required=True)
    parser.add_argument("-d", "--dolist", type=str, required=False, default="[]")
    parser.add_argument("--dolist_para", action="store_true")
    parser.add_argument("--group-paths", type=str, required=False, default="[]")
    parser.add_argument("--result-csv", type=str, required=False, default=None)
    parser.add_argument("--project-score-json", type=str, required=False, default=None)

    args = parser.parse_args()
    dirlist = json.loads(args.dirlist)
    dolist = set([_.replace(".json", "") for _ in json.loads(args.dolist)])
    dolist_para = args.dolist_para
    group_paths = json.loads(args.group_paths)
    print(f"Dolist set. {dolist}.")

    start_with_dict = {
        "gpt": GPTTest,
        "gemini": GeminiTest,
        "deepseek": DeepSeekTest,
    }

    project_id_list = [str(_) for _ in range(1, 21)]
    result_output_path = "experiments/"
    result_csv_path = args.result_csv or (
        result_output_path + f"projecteval-result-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    )
    Path(result_csv_path).parent.mkdir(parents=True, exist_ok=True)
    project_score_json_path = Path(args.project_score_json) if args.project_score_json else None
    project_score_rows = []
    file = open(result_csv_path, "w", encoding="utf-8", newline="")

    result_file = csv.DictWriter(
        file,
        delimiter=",",
        fieldnames=[
            "date",
            "model",
            "mode",
            "run_id",
            "timestamp",
            "level",
            "passed",
            "failed",
            "executed",
            "score",
        ],
    )
    result_file.writeheader()

    if group_paths:
        groups = [_load_group_from_answer_code(item) for item in group_paths]
    else:
        groups = []
        for date in dirlist:
            groups.extend(_discover_groups(result_output_path, date))

    for group in groups:
        run_id = str(group["run_id"])
        if dolist_para and run_id not in dolist:
            print(f"Skip {run_id}.")
            continue
        try:
            level = int(group["level"])
            if group["mode"] == "cascade" and level == 3:
                print("Skip cascade level 3")
                continue

            model = str(group["model"])
            if model.split("-")[0] in start_with_dict:
                model_class = start_with_dict[model.split("-")[0]]
                model_name = model
            else:
                model_class = OllamaTest
                model_name = model.replace("-", ":")

            tester = JudgeController(
                question_path="data/project_eval_project.json",
                answer_path=group["answer_code_path"],
                model_class=model_class,
                parameter_file_path=group["answer_parameter_path"],
                llm=model_name,
                device="GPU-e64683ee-8e58-13f4-b2aa-e88128cc3ef9",
            )

            tester.logger.info("Start:" + "-".join([group["date"], model, group["mode"], run_id]))
            initiate_command = {}
            requirements = {}

            for project_id in project_id_list:
                if project_id not in (str(_) for _ in range(16, 20)):
                    initiate_command[project_id] = [[]]
                    requirements[project_id] = ["django", "matplotlib", "pyperclip", "qrcode", "markdown"]
                else:
                    initiate_command[project_id] = []
                    requirements[project_id] = ["openpyxl", "pandas"]

            startfile_path = group.get("answer_startfile_path")
            if startfile_path and Path(startfile_path).exists():
                start_file_list = json.loads(Path(startfile_path).read_text(encoding="utf-8"))
            else:
                start_file_list = None
            score, score_table = tester.evaluate(
                initiate_command,
                requirements,
                project_id_list=project_id_list,
                start_file_list=start_file_list,
            )
            for row in score_table:
                project_score_rows.append(
                    {
                        **row,
                        "date": group["date"],
                        "model": model,
                        "mode": group["mode"],
                        "run_id": run_id,
                        "timestamp": run_id,
                        "level": level,
                    }
                )
            data = {
                "date": group["date"],
                "model": model,
                "mode": group["mode"],
                "run_id": run_id,
                "timestamp": run_id,
                "level": level,
                "passed": score["pass"],
                "failed": PROJECT_EVAL_DEFAULT_TEST_CASE - score["pass"],
                "executed": score["testcase"] if "testcase" in score else 0,
                "score": score["pass@1"] if "pass@1" in score else 0,
            }
            for key in data:
                data[key] = str(data[key])
            result_file.writerow(data)
            file.flush()
            if project_score_json_path:
                project_score_json_path.parent.mkdir(parents=True, exist_ok=True)
                project_score_json_path.write_text(
                    json.dumps(project_score_rows, indent=2),
                    encoding="utf-8",
                )
        except Exception as e:
            print(e)
