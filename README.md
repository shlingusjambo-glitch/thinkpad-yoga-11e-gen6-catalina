# ThinkPad Yoga 11e Gen 6 · macOS Catalina

OpenCore 1.0.8 configuration for macOS Catalina 10.15.7 on the Core m3-8100Y variant with Intel UHD 615, Intel Wireless-AC 9260, and Realtek ALC257 audio. The tested setup uses AppleALC layout 11. It includes F5/F6 brightness mappings, the BrightnessKeys driver, and an ELAN touchpad setting that removes the post-keypress pause.

## Build a recovery USB

On a Mac with Python 3, run from this repository:

```sh
python3 build_efi.py --recovery
```

The build downloads checksum-pinned OpenCore, kexts, and ACPI files from their upstream projects. With `--recovery`, it also downloads and verifies Catalina 10.15.7 Recovery directly from Apple. Copy the generated `EFI` and `com.apple.recovery.boot` folders from `build/ThinkPad-Catalina` to the root of a FAT32 USB drive. Copy the `tools` folder too if you want the internal-boot helper available on the USB.

In ThinkPad Setup, use UEFI boot and disable firmware Secure Boot. Press **F12** to choose the USB, then select the entry ending in **(dmg)** in OpenCore. Join your own Wi‑Fi in Recovery to download the installer payload. Install to a backed-up drive intended for Catalina.

## iServices

Each fresh build generates a local MacBookAir8,1 identity. To retain your existing identity, build with `--identity-from /path/to/your/config.plist`. Keep the generated output private. Before signing into Apple services on a fresh build, verify the generated serial, set ROM to the ThinkPad's hardware MAC address, and check for a built-in `en0` and working NVRAM. [Dortania’s iServices guide](https://dortania.github.io/OpenCore-Post-Install/universal/iservices.html)

## Boot from the internal drive

Once Catalina boots from USB, mount the internal disk’s EFI partition from Catalina. Check the correct disk with `diskutil list internal physical`, then use `sudo diskutil mount <identifier>`. Run the helper using the paths for your USB and internal EFI:

```sh
sudo /usr/bin/python /Volumes/CATALINA/tools/thinkpad-efi.py install /Volumes/CATALINA /Volumes/EFI
```

The helper verifies OpenCore and backs up any prior internal `OC` folder and `BOOTx64.efi`. Shut down, unplug the USB, then choose the internal UEFI drive from the **F12** menu. [Dortania’s internal boot guide](https://dortania.github.io/OpenCore-Post-Install/universal/oc2hdd.html)

If F5/F6 do not change brightness, try the other Fn Lock mode with **Fn+Esc**. The input helper also accepts `--quiet-ms 100` if you want some touchpad palm suppression during typing.

## Credits

The model-specific starting point was the [original ThinkPad guide by milktoast56](https://github.com/milktoast56/Lenovo-ThinkPad-Yoga-11e-Gen6-Hackintosh-EFI-guide). OpenCore, kexts, and ACPI downloads come from the projects listed in [dependencies.json](dependencies.json).
