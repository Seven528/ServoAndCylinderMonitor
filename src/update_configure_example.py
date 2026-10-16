import os
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'config'/ "configure.yaml"
TARGET = ROOT /  'config'/"configure.example.yaml"


def make_example(value):
    """保留结构，替换所有配置值。"""
    if isinstance(value, dict):
        return {
            key: make_example(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [make_example(item) for item in value]

    if value is None:
        return None

    # bool 是 int 的子类，因此需要先判断 bool。
    if isinstance(value, bool):
        return False

    if isinstance(value, int):
        return 0

    if isinstance(value, float):
        return 0.0

    return "CHANGE_ME"


def main():
    temporary_path = None

    try:
        # 防止真实配置被误提交，包括被 git add -f 加入的情况。
        tracked = subprocess.run(
            ["git", "ls-files", "--", SOURCE.relative_to(ROOT).as_posix()],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        if tracked.stdout.strip():
            print("ERROR: configure.yaml is tracked.")
            print(f"Run: git rm --cached -- {SOURCE.relative_to(ROOT).as_posix()}")
            return 1

        with SOURCE.open("r", encoding="utf-8-sig") as file:
            config = yaml.safe_load(file)

        if not isinstance(config, dict):
            print("ERROR: configure.yaml must contain a root mapping.")
            return 1

        example = make_example(config)

        content = (
            "# Auto-generated from configure.yaml.\n"
            "# Placeholder values only. Do not put credentials here.\n\n"
            + yaml.safe_dump(
                example,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        )

        # 内容没有变化时，不重复写入文件。
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != content:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=ROOT,
                prefix=".configure-example-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                file.write(content)

            os.replace(temporary_path, TARGET)
            temporary_path = None

        # 将生成的模板加入本次提交。
        # 获取生成文件的完整路径，并确认文件确实存在。
        target_path = TARGET.resolve(strict=True)

        # 从生成文件所在目录查找所属 Git 仓库。
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=target_path.parent,
            check=True,
            capture_output=True,
            text=True,
        )

        repo_root = Path(result.stdout.strip()).resolve()

        # 转换为相对于仓库根目录的路径，例如：
        # configure.example.yaml
        # 或 config/configure.example.yaml
        relative_path = target_path.relative_to(repo_root).as_posix()

        print(f"Generated file: {target_path}")
        print(f"Git repository: {repo_root}")
        print(f"Staging path: {relative_path}")

        # 从仓库根目录执行 git add。
        subprocess.run(
            ["git", "add", "--", relative_path],
            cwd=repo_root,
            check=True,
        )

    except FileNotFoundError:
        print("ERROR: configure.yaml or the Git executable was not found.")
        return 1

    except yaml.YAMLError:
        # 不打印原始异常，避免异常信息包含真实配置值。
        print("ERROR: Invalid YAML syntax in configure.yaml.")
        return 1

    except (OSError, UnicodeError, subprocess.CalledProcessError):
        print("ERROR: Failed to generate or stage configure.example.yaml.")
        return 1

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    print("OK: configure.example.yaml generated and staged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())