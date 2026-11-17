"""The local CLI follows the selected host release, not a development import."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_cli_loads_runtime_release_before_importing_cli(tmp_path):
    host = tmp_path / "host"
    release = tmp_path / "selected"
    checkout = tmp_path / "checkout"
    host.mkdir()
    for path, label in ((release, "selected"), (checkout, "wrong-checkout")):
        package = path / "mnemosyne"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "cli.py").write_text(
            "def main(args):\n"
            f"    print({label!r}, '|'.join(args))\n"
            "    return 0\n"
        )
    (host / "runtime.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        f"ROOT = Path({str(tmp_path / 'store-root')!r})\n"
        f"sys.path.insert(0, {str(release)!r})\n"
    )
    (host / "retrieval_config.py").write_text("def configure_environment(): pass\n")
    source = Path(__file__).resolve().parents[1] / "integrations/codex/cli.py"
    shutil.copyfile(source, host / "cli.py")
    result = subprocess.run(
        [sys.executable, str(host / "cli.py"), "status"],
        env={**os.environ, "PYTHONPATH": str(checkout)},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == (
        "selected --backend|sqlite|--store|"
        + str(tmp_path / "store-root/codex-memory") + "|status"
    )
