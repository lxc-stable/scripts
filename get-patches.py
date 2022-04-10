import sys
import yaml
import json
import subprocess

import requests


# Mostly for autodetecting the upstream projects we run the script inn
UPSTREAMS = {
        "lxd": "git@github.com:lxc/lxd.git",
        "lxc": "git@github.com:lxc/lxc.git",
        "lxcfs": "git@github.com:lxc/lxcfs.git",
}

# Snap channel we are tracking
CHANNEL = "candidate"

# The remote we push stable updates towards
REMOTE = "stable"


def fetch_all():
    b = subprocess.run(["git", "fetch", "--all"], capture_output=True)
    return str(b.stdout)


def get_remotes():
    b = subprocess.run(["git", "remote", "-v"], capture_output=True, text=True)
    ret = []
    for line in b.stdout.splitlines():
        if not line.split('\t')[-1]:
            continue
        remote = line.split('\t')[-1].split()[0]
        if remote in ret:
            continue
        ret.append(remote)
    return ret


def get_tags(prefix="", branch="master"):
    b = subprocess.run(["git", "tag", "--merged", branch], capture_output=True, text=True)
    out = b.stdout.splitlines()
    out = filter(lambda s: prefix in s, out)
    return list(out)


def tag_release(tag):
    b = subprocess.run(["git", "tag", "-m", "", "--sign", tag], capture_output=True, text=True)
    if b.returncode != 0:
        print(b.stdout)
        raise Exception("failed to tag release")
    print(f"Tagged release {tag}")
    return str(b.stdout)


def push_to_remote(branch, remote="stable"):
    print(f"Pushing branch {branch} to remote stable {remote}")
    b = subprocess.run(["git", "push", "--tags", remote, branch])
    if b.returncode != 0:
        print(b.stdout)
        raise Exception("failed to tag release")


def change_branch(branch, start_branch):
    subprocess.run(["git", "checkout", '-b', branch, start_branch])


def apply_patch(patches):
    new_commits = False
    for patch in patches:
        b = subprocess.run(["git", "log", "--all", f"--grep={patch}"], capture_output=True, text=True)
        if b.stdout:
            print(f"Skipping previously applied patch {patch}")
            continue
        b = subprocess.run(["git", "cherry-pick", "-x", patch], capture_output=True, text=True)
        print(f"Applying patch {patch}")
        if b.returncode == 0:
            new_commits = True
            continue
        if "nothing to commit" in b.stdout:
            subprocess.run(["git", "cherry-pick", "--abort"], capture_output=True, text=True)
            continue
        print(b.stdout)
        raise Exception("failed to apply cherry-pick")
    return new_commits


def get_revisions():
    url = "https://api.snapcraft.io/v2/snaps/info/lxd"
    r = requests.get(url, headers={"Snap-Device-Series": "16"})
    print(r.json()["channel-map"])
    return

# print(get_revisions())
# import sys
# sys.exit()
# SNAP_URL = "https://api.snapcraft.io/api/v1/snaps/details/lxd?channel=candidate"
# r = requests.get(SNAP_URL, headers={"X-Ubuntu-Series": "16"})

def get_cherry_picks(s):
    ret = []
    for line in s.split("\n"):
        if "git cherry-pick" in line:
            ret.append(line.split()[2])
    return ret


def get_backports(upstream=''):
    SNAP_URL = f"https://api.snapcraft.io/api/v1/snaps/details/lxd?channel={CHANNEL}"
    r = requests.get(SNAP_URL, headers={"X-Ubuntu-Series": "16"})
    HASH = r.json()["version"].split("-")[-1]

    URL = f"https://raw.githubusercontent.com/lxc/lxd-pkg-snap/{HASH}/snapcraft.yaml"
    r = requests.get(URL)
    body = r.content

    APPS = ["lxd", "lxc", "lxcfs"]
    OUTS = []
    OUT = {
            "app": "",
            "tag": "",
            "branch_name": "",
            "backports": [],
    }

    y = yaml.safe_load(body)
    for k, v in y["parts"].items():
        if k not in APPS:
            continue
        app = y["parts"][k]
        OUT["app"] = k
        version = app["source-tag"].split("-")[-1]
        backports = get_cherry_picks(app["override-build"])
        d = {"app": k,
             "tag": f"{k}-{version}",
             "branch_name": f"stable-{version}",
             "backports": backports}
        if k == upstream:
            return [d]
        OUTS.append(d)
    return OUTS


# TODO: Less dict shenanigans

# Autodetect the project we are inside
APP = ''
remotes = get_remotes()
for app, remote in UPSTREAMS.items():
    if remote in remotes:
        APP = app
        break

b = get_backports(APP)
change_branch(b[0]['branch_name'], b[0]['tag'])

new_commits = apply_patch(b[0]['backports'])
if not new_commits:
    print("No new commits to backport")
    sys.exit(0)

minor = len(get_tags(prefix=b[0]['tag']))
new_tag = f"{b[0]['tag']}.{minor}"
tag_release(new_tag)
push_to_remote(b[0]['branch_name'])
