import os
import shutil
import subprocess
import argparse
from git import Repo
import io
import time
import requests
import marshal
import importlib
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.align import Align

console = Console()
REPO_URL = "https://github.com/msgpack/msgpack-python.git"
CLONE_DIR = "./msgpack-python"
PATCH_FILE = "./patch.diff"
ORIGINAL_FILE = os.path.join(CLONE_DIR, "msgpack", "_unpacker.pyx")
BACKUP_FILE = ORIGINAL_FILE + ".bak"
API_ENDPOINT = 'https://api.pylingual.io'

def apply_simple_patch(original_file, patch_file, output_file=None):
    with open(original_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    with open(patch_file, 'r', encoding='utf-8') as f:
        patch = f.readlines()

    import re
    changes = []
    i = 0
    while i < len(patch):
        line = patch[i]
        m = re.match(r'^(\d+)([ac])(\d+)(?:,(\d+))?', line)
        if m:
            orig_line = int(m.group(1)) - 1
            op = m.group(2)
            if op == 'a':
                added = []
                i += 1
                while i < len(patch) and patch[i].startswith('>'):
                    added.append(patch[i][2:])
                    i += 1
                changes.append(('a', orig_line, added))
            elif op == 'c':
                i += 1
                removed = []
                while i < len(patch) and patch[i].startswith('<'):
                    removed.append(patch[i][2:])
                    i += 1
                if i < len(patch) and patch[i].startswith('---'):
                    i += 1
                added = []
                while i < len(patch) and patch[i].startswith('>'):
                    added.append(patch[i][2:])
                    i += 1
                changes.append(('c', orig_line, len(removed), added))
        else:
            i += 1

    for change in reversed(changes):
        if change[0] == 'a':
            idx, added = change[1], change[2]
            lines[idx + 1:idx + 1] = added
        elif change[0] == 'c':
            idx, nremove, added = change[1], change[2], change[3]
            lines[idx:idx + nremove] = added

    for i in range(len(lines) - 1):
        if not lines[i].endswith('\n'):
            lines[i] += '\n'
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'

    if output_file is None:
        output_file = original_file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def clone_repo():
    if os.path.exists(CLONE_DIR):
        console.log("[yellow]Repository already cloned.")
    else:
        with console.status("[bold green]Cloning repository..."):
            Repo.clone_from(REPO_URL, CLONE_DIR)
            console.log("[green]Repository cloned successfully.")

def apply_patches():
    if not os.path.exists(BACKUP_FILE):
        shutil.copyfile(ORIGINAL_FILE, BACKUP_FILE)
        apply_simple_patch(ORIGINAL_FILE, PATCH_FILE)
        console.log("[green]Patch applied to file.")
    else:
        console.log("[yellow]File already patched.")

def install_package():
    table = Table(title="Installing modified msgpack...", box=None, expand=True)
    table.add_column("Step", style="cyan", no_wrap=True)
    table.add_column("Output", style="white")

    steps = [("Running Cython", ["cython", 'msgpack\\_cmsgpack.pyx']),("Installing with pip", ["pip", "install", "-e", "."]),]
    with Live(table, refresh_per_second=4, console=console):
        for step_name, cmd in steps:
            table.add_row(f"[bold]{step_name}[/bold]", "")
            process = subprocess.Popen(cmd, cwd=CLONE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            for line in process.stdout:
                table.add_row("", Text(line.strip()))

            process.wait()
            if process.returncode == 0:
                table.add_row("", "[green]✔ Success[/green]")
            else:
                table.add_row("", "[red]✘ Failed[/red]")
                raise subprocess.CalledProcessError(process.returncode, cmd)

    console.log("[green]Modified msgpack installed.")
def is_custom_msgpack_installed():
    try:
        import msgpack
        installed_path = os.path.abspath(msgpack.__file__)
        expected_path = os.path.abspath(CLONE_DIR)
        return expected_path in installed_path
    except ImportError:
        return False

def _convert_pyc_to_src(pyc_data):
    buffered_reader = io.BytesIO(pyc_data)

    try:
        with console.status("[bold blue]Uploading .pyc to Pylingual..."):
            j = requests.post(f'{API_ENDPOINT}/upload', files={'file': buffered_reader}).json()
            if not j['success']:
                return None, j.get('message', 'Unknown error during upload')
            identifier = j['identifier']

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Converting with Pylingual...", start=False)
            progress.start_task(task)
            while True:
                j = requests.get(f'{API_ENDPOINT}/get_progress?identifier={identifier}').json()
                if not j['success']:
                    return None, j.get('message', 'Error checking progress')
                if j['stage'] == 'done':
                    break
                time.sleep(1)

        j = requests.get(f'{API_ENDPOINT}/view?identifier={identifier}').json()
        code = j['editor_content']['editor_tabs'][0]['editor_content']
        return code, None
    except Exception as e:
        return None, str(e)

def run_code(target_pye_file):
    target_pye_file = os.path.abspath(target_pye_file)
    filecwd = os.path.dirname(target_pye_file)
    pye_filename = os.path.basename(target_pye_file)
    filename_py = os.path.join(filecwd, ".".join(pye_filename.split(".")[:-1]) + ".py")

    if os.path.exists(target_pye_file):
        with console.status("[cyan]Running sourcedefender import to extract source..."):
            with open(filename_py, 'w') as output:
                result = subprocess.run(
                    ["python", "-c", f"import sourcedefender; import {pye_filename}"],
                    cwd=filecwd, check=False, stdout=output, stderr=subprocess.DEVNULL
                )
        console.log(f"[green]Raw output saved to [bold]{filename_py}[/bold]")

        with open(filename_py, "r") as f:
            file_data = f.read()

        if file_data.startswith("b'"):
            file_data = file_data.strip().split("b'", 1)[1][:-1]
            byte_data = bytes(file_data, "utf-8").decode("unicode_escape").encode("latin1")
            code_object = marshal.loads(byte_data)
            pyc_data = importlib._bootstrap_external._code_to_timestamp_pyc(code_object)

            code, error = _convert_pyc_to_src(pyc_data)
            if code is None:
                console.log(f"[red]Failed to reconstruct source: {error}")
                return

            filtered_code = "\n".join(
                line for line in code.splitlines() if not line.strip().startswith("#")
            )
            outfile_path = os.path.join(filecwd, ".".join(pye_filename.split(".")[:-1]) + "_pylingual.py")
            with open(outfile_path, "w", encoding="utf-8") as f:
                f.write(filtered_code)

            console.log(f"[bold green]Reconstructed source code saved to [bold]{outfile_path}[/bold]")
        else:
            console.log(f"[bold green]Source code recovered at [bold]{filename_py}[/bold]")

def main():
    parser = argparse.ArgumentParser(description="Sourcedefender Restore")
    parser.add_argument('file', type=str, help="Path to the .pye file to run")
    args = parser.parse_args()
    banner_text = """[bold cyan]Sourcedefener Restore Tool[/bold cyan]
    [white]by GsDeluxe & HWYKagiru[/white]
    [magenta]https://github.com/GsDeluxe/Sourcedefener-Restore[/magenta]"""

    console.print(Panel.fit(Align.center(banner_text),padding=(1, 4)))
    if not is_custom_msgpack_installed():
        clone_repo()
        apply_patches()
        install_package()
    else:
        console.log("[bold green]Custom msgpack already installed.")

    run_code(args.file)

if __name__ == "__main__":
    main()
