#!/usr/bin/env python3
"""Prepare, package and publish a tested main commit. No force pushes."""
import argparse
import datetime as dt
import fnmatch
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile
from zoneinfo import ZoneInfo

DATE_TAG = re.compile(r"v(\d{4})\.(\d{1,2})\.(\d{1,2})\.(\d+)$")


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def git(*args):
    return run("git", *args).stdout.strip()


def next_tag(tags, now):
    day = (now.year, now.month, now.day)
    versions = [tuple(map(int, m.groups())) for tag in tags
                if (m := DATE_TAG.fullmatch(tag))]
    if versions and max(versions)[:3] > day:
        day = max(versions)[:3]
    revision = max((v[3] for v in versions if v[:3] == day), default=0) + 1
    return "v" + ".".join(map(str, (*day, revision)))


def release_info(repo, tag):
    result = run("gh", "api", f"repos/{repo}/releases/tags/{tag}", check=False)
    if result.returncode:
        if "(HTTP 404)" in result.stderr:
            return None
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def excluded(path, rules):
    result = False
    # Same suffix/prefix matching and last-match-wins rules as core/updater.lua.
    for raw in rules.splitlines():
        rule = raw.strip()
        if not rule or rule.startswith("#"):
            continue
        negate = rule.startswith("!")
        pattern = rule.removeprefix("!").rstrip("/")
        if not pattern:
            continue
        parts = path.split("/")
        if any(fnmatch.fnmatchcase("/".join(parts[start:end]), pattern)
               for start in range(len(parts)) for end in range(start + 1, len(parts) + 1)):
            result = not negate
    return result


def package(ref, destination):
    """Read committed files only; never read a worktree configuration.lua."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    rules = git("show", f"{ref}:.releaseignore")
    data = subprocess.check_output(["git", "archive", "--format=tar", ref])
    archive = destination / f"assistant.koplugin-{ref}.zip"
    with tarfile.open(fileobj=io.BytesIO(data)) as source, zipfile.ZipFile(
            archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for entry in source:
            if not entry.isfile() or excluded(entry.name, rules):
                continue
            if Path(entry.name).name in {"configuration.lua", "apikeys.lua"}:
                raise RuntimeError("Refusing to package a user-owned credential file")
            info = zipfile.ZipInfo("assistant.koplugin/" + entry.name)
            info.external_attr = (0o100000 | entry.mode) << 16
            target.writestr(info, source.extractfile(entry).read(),
                            compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as result:
        assert "assistant.koplugin/main.lua" in result.namelist()
        meta = result.read("assistant.koplugin/_meta.lua").decode()
        assert f'version = "{ref.removeprefix("v")}"' in meta
    return archive


def prepare(state_path, repo, sync):
    if git("status", "--porcelain"):
        raise RuntimeError("A clean checkout is required")
    git("fetch", "origin", "main", "--tags")
    git("fetch", "https://github.com/omer-faruq/assistant.koplugin.git",
        "main:refs/remotes/upstream/main")
    base = git("rev-parse", "origin/main")
    git("switch", "-C", "automation/candidate", base)
    if sync:
        merged = run("git", "merge", "--no-edit", "refs/remotes/upstream/main", check=False)
        if merged.returncode:
            raise RuntimeError("Upstream merge conflict; main was not changed.\n"
                               + merged.stdout + merged.stderr)
    candidate = git("rev-parse", "HEAD")
    upstream = git("merge-base", "HEAD", "refs/remotes/upstream/main")
    matching = [t for t in git("tag", "--points-at", "HEAD").splitlines()
                if DATE_TAG.fullmatch(t)]
    if len(matching) > 1:
        raise RuntimeError("Multiple date release tags on candidate")
    state = dict(base=base, upstream=upstream, repo=repo, noop=False)
    if matching:
        tag = matching[0]
        release = release_info(repo, tag)
        state["noop"] = bool(release and not release["draft"])
    else:
        tag = next_tag(git("tag", "--list").splitlines(),
                       dt.datetime.now(ZoneInfo("Asia/Taipei")))
        meta = Path("_meta.lua")
        source, count = re.subn(r'version\s*=\s*"[^"]+"',
                               f'version = "{tag[1:]}"', meta.read_text())
        if count != 1:
            raise RuntimeError("Expected exactly one plugin version")
        meta.write_text(source)
        git("add", "_meta.lua")
        git("commit", "-m", f"chore: prepare release {tag}")
        candidate = git("rev-parse", "HEAD")
    state.update(candidate=candidate, tag=tag)
    Path(state_path).write_text(json.dumps(state))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as stream:
            stream.write(f"active={str(not state['noop']).lower()}\n")
    print(json.dumps(state, indent=2))


def publish(state_path, directory):
    state = json.loads(Path(state_path).read_text())
    if state["noop"]:
        return
    tag, candidate, repo = state["tag"], state["candidate"], state["repo"]
    if git("rev-parse", "HEAD") != candidate or git("status", "--porcelain"):
        raise RuntimeError("Candidate changed after validation")
    git("fetch", "origin", "main", "--tags")
    if git("rev-parse", "origin/main") != state["base"]:
        raise RuntimeError("main changed during validation; rerun against the new main")
    existing = run("git", "rev-parse", "--verify", f"refs/tags/{tag}", check=False)
    if existing.returncode == 0 and existing.stdout.strip() != candidate:
        raise RuntimeError("Release tag already points to a different commit")
    if existing.returncode:
        git("tag", tag, candidate)
    archive = package(tag, directory)
    # Normal fast-forward push is the final race guard; include the tag atomically.
    git("push", "--atomic", "origin", f"HEAD:refs/heads/main", f"refs/tags/{tag}")
    release = release_info(repo, tag)
    if release and not release["draft"]:
        print(f"{tag} is already published")
        return
    earlier = [t for t in git("tag", "--merged", "HEAD").splitlines()
               if DATE_TAG.fullmatch(t) and t != tag]
    previous = max(earlier, key=lambda t: tuple(map(int, DATE_TAG.fullmatch(t).groups()))) if earlier else state["upstream"]
    changes = git("log", "--format=- %s (%h)", f"{previous}..HEAD")
    notes = Path(directory) / "release-notes.md"
    notes.write_text(f"Custom KOReader assistant release {tag}.\n\n"
                     f"Upstream: {state['upstream']}\nSource: {candidate}\n\n{changes}\n\n"
                     "Validation: full Lua suite, LuaLS diagnostics, Markdown UI "
                     "regressions, maintenance tests and package checks passed.\n"
                     f"KOReader: {os.environ.get('KOREADER_VERSION', 'see workflow log')}\n"
                     f"Workflow: https://github.com/{repo}/actions/runs/"
                     f"{os.environ.get('GITHUB_RUN_ID', '')}\n\n"
                     "Install the ZIP once; subsequent updates use the plugin OTA menu. "
                     "Select a previous date tag in that menu to roll back.\n")
    if not release:
        run("gh", "release", "create", tag, "--repo", repo, "--verify-tag",
            "--draft", "--title", tag, "--notes-file", str(notes))
    run("gh", "release", "upload", tag, str(archive), "--repo", repo, "--clobber")
    run("gh", "release", "edit", tag, "--repo", repo, "--draft=false", "--latest")
    print(f"Published {tag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "publish"])
    parser.add_argument("--state", required=True)
    parser.add_argument("--repo", default="edenz223/assistant.koplugin")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--output", default=os.environ.get("RUNNER_TEMP", "/tmp"))
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            prepare(args.state, args.repo, args.sync)
        else:
            publish(args.state, args.output)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.stderr or str(error))
