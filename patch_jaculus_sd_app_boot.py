from pathlib import Path

# Applied after patch_jaculus_sd.py and patch_jaculus_sd_stable.py.
#
# Goal: treat the external SD card as the application's primary persistent
# storage, while keeping the Jaculus runtime and installed native/JS libraries
# in the normal internal firmware/code area.
#
# The JavaScript application is started DIRECTLY from the SD card instead of
# first running a tiny JS launcher and then dynamic-importing the SD program.
# This avoids keeping an extra launcher module alive and makes the SD application
# the machine entry point.
#
# Jaculus' module loader reads an entire JS module into a C++ std::string before
# passing it to QuickJS. The Octal-PSRAM target normally uses CAPS_ALLOC mode,
# where ordinary C/C++ malloc/new allocations stay in internal RAM. Switch to
# SPIRAM_USE_MALLOC so large source buffers can use PSRAM as well, reducing the
# chance of std::bad_alloc while compiling applications stored on SD.

main = Path("firmware/main/main.cpp")
text = main.read_text()

old_start = '''    if (startMachine) {
        device.startMachine("");
    }
'''
new_start = '''    if (startMachine) {
        jac::Logger::log("Starting RoboDeck application directly from /sd/robodeck/software/main.js");
        device.startMachine("/sd/robodeck/software/main.js");
    }
'''
if old_start not in text:
    raise SystemExit("Could not find default device.startMachine block")
text = text.replace(old_start, new_start, 1)
main.write_text(text)

sdkconfig = Path("firmware/sdkconfig.defaults-esp32s3-octal")
config = sdkconfig.read_text()
old_psram = "CONFIG_SPIRAM_USE_CAPS_ALLOC=y"
new_psram = "CONFIG_SPIRAM_USE_MALLOC=y"
if old_psram not in config:
    raise SystemExit("Could not find CONFIG_SPIRAM_USE_CAPS_ALLOC in Octal PSRAM defaults")
config = config.replace(old_psram, new_psram, 1)
sdkconfig.write_text(config)

print("Applied direct SD application boot and PSRAM-backed malloc configuration")
