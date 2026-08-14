#!/usr/bin/env python3
"""Install an immutable, commit-addressed local grounded-role runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def install(root: Path, base: Path) -> Path:
    root = root.resolve()
    base = base.expanduser().resolve()
    if base == root or root in base.parents:
        raise ValueError("grounded runtime base must be outside the repository")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("grounded runtime installation requires a clean committed checkout")
    commit = _git(root, "rev-parse", "HEAD")
    if len(commit) != 40:
        raise ValueError("grounded runtime commit is invalid")
    destination = base / commit
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    try:
        tracked = _git(
            root,
            "ls-tree",
            "-r",
            "--name-only",
            commit,
            "--",
            "src/mnemosyne",
        ).splitlines()
        if not tracked:
            raise ValueError("grounded runtime commit contains no Mnemosyne package")
        for relative in tracked:
            target = destination / "lib" / Path(relative).relative_to("src")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                subprocess.run(
                    ["git", "show", f"{commit}:{relative}"],
                    cwd=root,
                    capture_output=True,
                    check=True,
                ).stdout
            )
        bin_dir = destination / "bin"
        bin_dir.mkdir(mode=0o700)
        libexec = destination / "libexec"
        libexec.mkdir(mode=0o700)
        sources = {
            "role-llm": root / "infra" / "providers" / "role-llm.py",
            "role-ladder": root / "infra" / "providers" / "role-ladder.py",
        }
        files: dict[str, str] = {}
        for name, source in sources.items():
            implementation = libexec / f"{name}.py"
            relative = source.relative_to(root)
            implementation.write_bytes(
                subprocess.run(
                    ["git", "show", f"{commit}:{relative.as_posix()}"],
                    cwd=root,
                    capture_output=True,
                    check=True,
                ).stdout
            )
            implementation.chmod(0o400)
            launcher = bin_dir / name
            launcher.write_text(
                "#!/usr/bin/env python3\n"
                "import runpy,sys\n"
                "sys.dont_write_bytecode=True\n"
                "from pathlib import Path\n"
                "root=Path(__file__).resolve().parents[1]\n"
                "sys.path.insert(0,str(root/'lib'))\n"
                f"runpy.run_path(str(root/'libexec'/'{name}.py'),run_name='__main__')\n"
            )
            launcher.chmod(0o500)
            for target in (implementation, launcher):
                files[str(target.relative_to(destination))] = hashlib.sha256(target.read_bytes()).hexdigest()
        for path in (destination / "lib").rglob("*"):
            if path.is_symlink():
                raise ValueError("grounded runtime source contains a symlink")
            if path.is_file():
                path.chmod(stat.S_IRUSR)
                files[str(path.relative_to(destination))] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {"commit": commit, "files": dict(sorted(files.items())), "schema": "grounded-runtime-v1"}
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
        manifest_path.chmod(0o400)
        for directory in sorted(
            (path for path in destination.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(0o500)
        destination.chmod(0o500)
        return destination
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("~/.local/share/mnemosyne/grounded-runtime"),
    )
    args = parser.parse_args(argv)
    print(install(args.repo, args.base))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
