#!/usr/bin/env python3
"""Assemble the Catalina EFI from verified upstream releases on macOS."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import plistlib
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
DEPENDENCIES = json.loads((ROOT / "dependencies.json").read_text())


def download(item, destination):
    subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                    "--retry", "2", "--output", str(destination), item["url"]], check=True)
    digest = hashlib.sha256()
    with destination.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != item["sha256"]:
        raise ValueError("Checksum mismatch: " + item["url"])
    return destination


def fetch_release(release, scratch):
    name, item = release
    archive = download(item, scratch / (name + ".zip"))
    unpacked = scratch / name
    subprocess.run(["ditto", "-x", "-k", str(archive), str(unpacked)], check=True)
    return name, unpacked


def set_identity(config, opencore, existing):
    generic = config["PlatformInfo"]["Generic"]
    keys = ("MLB", "ROM", "SystemSerialNumber", "SystemUUID")
    if existing:
        with existing.open("rb") as stream:
            previous = plistlib.load(stream)["PlatformInfo"]["Generic"]
        if previous["SystemProductName"] != generic["SystemProductName"]:
            raise ValueError("The prior EFI must use " + generic["SystemProductName"])
        if not all(previous[key] for key in keys) or len(previous["ROM"]) != 6:
            raise ValueError("The prior config is missing a complete Mac identity.")
        generic.update({key: previous[key] for key in keys})
        return

    macserial = opencore / "Utilities/macserial/macserial"
    macserial.chmod(0o755)
    result = subprocess.check_output([str(macserial), "-m", generic["SystemProductName"],
                                      "-n", "1"], text=True)
    serial, mlb = (field.strip() for field in result.split("|"))
    generic.update(SystemSerialNumber=serial, MLB=mlb, ROM=b"\x02" + secrets.token_bytes(5),
                   SystemUUID=str(uuid.uuid4()).upper())


def build(output, recovery, identity_from):
    if output.exists():
        raise FileExistsError("Output folder already exists: " + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".efi-build-") as temporary:
        scratch = Path(temporary)
        with ThreadPoolExecutor(max_workers=5) as pool:
            releases = dict(pool.map(lambda item: fetch_release(item, scratch),
                                     DEPENDENCIES["releases"].items()))
        media = scratch / "media"
        oc = media / "EFI/OC"
        for path in ("EFI/BOOT", "EFI/OC/ACPI", "EFI/OC/Drivers", "EFI/OC/Kexts", "tools"):
            (media / path).mkdir(parents=True)
        opencore = releases["OpenCorePkg"]
        release_efi = opencore / "X64/EFI"
        for path in ("BOOT/BOOTx64.efi", "OC/OpenCore.efi"):
            shutil.copyfile(release_efi / path, media / "EFI" / path)
        config = plistlib.loads((ROOT / "config.plist").read_bytes())
        set_identity(config, opencore, identity_from)
        (oc / "config.plist").write_bytes(plistlib.dumps(config, sort_keys=False))
        for driver in config["UEFI"]["Drivers"]:
            name = driver["Path"]
            shutil.copyfile(release_efi / "OC/Drivers" / name, oc / "Drivers" / name)
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda pair: download(pair[1], oc / "ACPI" / pair[0]),
                          DEPENDENCIES["acpi"].items()))
        for name, item in DEPENDENCIES["releases"].items():
            for kext in item["kexts"]:
                matches = list(releases[name].rglob(kext))
                if len(matches) != 1:
                    raise ValueError("Expected one upstream bundle for " + kext)
                shutil.copytree(matches[0], oc / "Kexts" / kext, symlinks=True)
        tools = media / "tools"
        shutil.copyfile(opencore / "Utilities/ocvalidate/ocvalidate", tools / "ocvalidate")
        (tools / "ocvalidate").chmod(0o755)
        helper = tools / "thinkpad-efi.py"
        shutil.copyfile(ROOT / "tools" / helper.name, helper)
        subprocess.run([sys.executable, str(helper), "input", str(oc)], check=True)
        # Backups are useful on a live EFI. The output here is a clean build.
        for backup in oc.glob("thinkpad-input-backup-*"):
            shutil.rmtree(backup)
        if recovery:
            subprocess.run([sys.executable, str(opencore / "Utilities/macrecovery/macrecovery.py"),
                            "-o", str(media / "com.apple.recovery.boot"), "-b",
                            "Mac-00BE6ED71E35EB86", "-m", "00000000000000000", "download"],
                           check=True)
        shutil.copyfile(ROOT / "README.md", media / "START-HERE.md")
        media.rename(output)
    print("Built " + str(output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/ThinkPad-Catalina")
    parser.add_argument("--recovery", action="store_true", help="Download Apple's signed Catalina recovery")
    parser.add_argument("--identity-from", type=Path, metavar="CONFIG",
                        help="Preserve the Mac identifiers from your own existing EFI config")
    args = parser.parse_args()
    try:
        build(args.output.resolve(), args.recovery, args.identity_from)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, "Build failed: " + str(error) + "\n")
