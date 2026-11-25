#!/usr/bin/python
from __future__ import print_function

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
KEYBOARD = "VoodooPS2Controller.kext/Contents/PlugIns/VoodooPS2Keyboard.kext"
TRACKPAD = "VoodooPS2Controller.kext/Contents/PlugIns/VoodooPS2Trackpad.kext"
INFO = "Contents/Info.plist"


def load(raw):
    if hasattr(plistlib, "loads"):
        return plistlib.loads(raw)
    return plistlib.readPlistFromString(raw)


def read_plist(path):
    return load(subprocess.check_output(
        ["/usr/bin/plutil", "-convert", "xml1", "-o", "-", path]))


def stage_plist(path, value):
    if hasattr(plistlib, "dumps"):
        raw = plistlib.dumps(value, sort_keys=False)
    else:
        raw = plistlib.writePlistToString(value)
    with tempfile.NamedTemporaryFile(dir=os.path.dirname(path), suffix=".plist",
                                     delete=False) as staged:
        staged.write(raw)
    try:
        subprocess.check_call(["/usr/bin/plutil", "-lint", staged.name])
    except Exception:
        os.unlink(staged.name)
        raise
    return staged.name


def validate(oc):
    if not os.path.isfile(os.path.join(oc, "OpenCore.efi")):
        raise ValueError("OpenCore.efi is missing from " + oc)
    subprocess.check_call([os.path.join(HERE, "ocvalidate"),
                           os.path.join(oc, "config.plist")])


def profile(plist, driver_class):
    personality = next(p for p in plist["IOKitPersonalities"].values()
                       if p.get("IOClass") == driver_class)
    return personality["Platform Profile"]["Default"]


def tune(oc, quiet_ms):
    validate(oc)
    config = read_plist(os.path.join(oc, "config.plist"))
    names = {entry["BundlePath"] for entry in config["Kernel"]["Add"] if entry["Enabled"]}
    if not {KEYBOARD, TRACKPAD}.issubset(names):
        raise ValueError("The expected VoodooPS2 keyboard and touchpad entries are missing.")

    keyboard_path = os.path.join(oc, "Kexts", KEYBOARD, INFO)
    trackpad_path = os.path.join(oc, "Kexts", TRACKPAD, INFO)
    keyboard = read_plist(keyboard_path)
    trackpad = read_plist(trackpad_path)
    keys = profile(keyboard, "ApplePS2Keyboard")
    mapping = keys.setdefault("Custom ADB Map", [])
    mapping[:] = [line for line in mapping
                  if line.split("=", 1)[0].strip().lower() not in ("3f", "40")]
    mapping.extend(("3f=6b;F5 display brightness down",
                    "40=71;F6 display brightness up"))
    profile(trackpad, "ApplePS2Elan")["QuietTimeAfterTyping"] = quiet_ms * 1000000

    backup = tempfile.mkdtemp(prefix="thinkpad-input-backup-", dir=oc)
    changes = [(keyboard_path, keyboard, "Keyboard-Info.plist"),
               (trackpad_path, trackpad, "Trackpad-Info.plist")]
    staged = []
    committed = []
    try:
        for path, data, backup_name in changes:
            original = os.path.join(backup, backup_name)
            shutil.copyfile(path, original)
            staged.append((stage_plist(path, data), path, original))
        for temp, path, original in staged:
            os.rename(temp, path)
            committed.append((original, path))
    except Exception:
        for original, path in committed:
            shutil.copyfile(original, path)
        raise
    finally:
        for temp, _, _ in staged:
            if os.path.isfile(temp):
                os.unlink(temp)
    print("Input backups saved at " + backup)
    print("Set F5/F6 brightness mapping and touchpad typing delay to {} ms.".format(quiet_ms))


def disk_info(mount):
    info = load(subprocess.check_output(["/usr/sbin/diskutil", "info", "-plist", mount]))
    if os.path.realpath(info.get("MountPoint", "")) != mount:
        raise ValueError("Pass a mounted volume root: " + mount)
    return info


def skip_metadata(_, names):
    return [name for name in names if name.startswith(
        ("._", "catalina-audio-backup-", "thinkpad-input-backup-"))
        or name == ".DS_Store"]


def migrate(source, target):
    source_disk, target_disk = disk_info(source), disk_info(target)
    if source_disk.get("Internal") is not False:
        raise ValueError("The source must be your external OpenCore USB.")
    partition_types = (target_disk.get("Content"), target_disk.get("PartitionType"))
    if (target_disk.get("Internal") is not True or "EFI" not in partition_types
            or target_disk.get("DeviceIdentifier") == source_disk.get("DeviceIdentifier")):
        raise ValueError("The destination must be the mounted EFI partition of the internal drive.")

    source_efi = os.path.join(source, "EFI")
    source_oc = os.path.join(source_efi, "OC")
    source_boot = os.path.join(source_efi, "BOOT", "BOOTx64.efi")
    validate(source_oc)
    target_efi = os.path.join(target, "EFI")
    target_oc = os.path.join(target_efi, "OC")
    target_boot_dir = os.path.join(target_efi, "BOOT")
    target_boot = os.path.join(target_boot_dir, "BOOTx64.efi")

    if not os.path.isdir(target_boot_dir):
        os.makedirs(target_boot_dir)
    staging = tempfile.mkdtemp(prefix=".thinkpad-efi-stage-", dir=target)
    backup = tempfile.mkdtemp(prefix="thinkpad-boot-backup-", dir=target)
    old_paths, new_paths = [], []
    try:
        staged_oc = os.path.join(staging, "OC")
        staged_boot = os.path.join(staging, "BOOTx64.efi")
        shutil.copytree(source_oc, staged_oc, ignore=skip_metadata)
        shutil.copyfile(source_boot, staged_boot)
        validate(staged_oc)
        for dest in (target_oc, target_boot):
            if os.path.exists(dest):
                saved = os.path.join(backup, os.path.basename(dest))
                os.rename(dest, saved)
                old_paths.append((saved, dest))
        for staged, dest in ((staged_oc, target_oc), (staged_boot, target_boot)):
            os.rename(staged, dest)
            new_paths.append(dest)
    except Exception:
        for dest in reversed(new_paths):
            os.rename(dest, os.path.join(staging, os.path.basename(dest)))
        for saved, dest in reversed(old_paths):
            os.rename(saved, dest)
        raise
    finally:
        shutil.rmtree(staging)
    print("Installed and validated the USB's working OpenCore on the internal EFI.")
    print("Any previous OC folder or BOOTx64.efi was saved at " + backup)


def main():
    parser = argparse.ArgumentParser(description="Set up internal boot and input on the Catalina ThinkPad.")
    sub = parser.add_subparsers(dest="operation")
    install = sub.add_parser("install", help="Copy the working USB OpenCore to the internal EFI")
    install.add_argument("usb_volume")
    install.add_argument("internal_efi_volume")
    fix = sub.add_parser("input", help="Set F5/F6 brightness and adjust the ELAN typing delay")
    fix.add_argument("oc_folder")
    fix.add_argument("--quiet-ms", type=int, choices=(0, 100, 500), default=0,
                     help="Touchpad pause after typing in milliseconds (default: 0)")
    args = parser.parse_args()
    try:
        if args.operation == "install":
            migrate(os.path.realpath(args.usb_volume), os.path.realpath(args.internal_efi_volume))
        elif args.operation == "input":
            tune(os.path.realpath(args.oc_folder), args.quiet_ms)
        else:
            parser.error("Choose install or input.")
    except (IOError, OSError, ValueError, KeyError, StopIteration,
            subprocess.CalledProcessError) as error:
        print("EFI operation failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
