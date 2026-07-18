from pathlib import Path

# Applied after patch_jaculus_sd.py.
#
# The proven working configuration mounts the SD card late, during Jaculus
# machine initialization. The important lifecycle detail is that Jaculus can
# stop and recreate the JavaScript Machine without rebooting the ESP32. The SD
# mount is firmware-global, so it must stay mounted across those Machine
# restarts. Re-mounting on every Machine::initialize() can leave /sd missing
# after VS Code "Build, Flash & Monitor" / program restarts.
#
# This patch therefore:
#   1. removes the early boot mount added by patch_jaculus_sd.py;
#   2. mounts /sd as the final Machine initialization feature;
#   3. mounts only when sd_card == nullptr, preserving a good mount across
#      subsequent Jaculus Machine restarts.

main = Path("firmware/main/main.cpp")
text = main.read_text()

early_mount = r'''    esp_err_t sd_err = mountSdCard();
    if (sd_err == ESP_OK) {
        jac::Logger::log("SD card mounted at /sd (SPI <= 4 MHz, POSIX fs)");
    }
    else {
        jac::Logger::log(std::string("SD card mount failed: ") + esp_err_to_name(sd_err));
    }
'''
if early_mount not in text:
    raise SystemExit("Could not find early SD mount block")
text = text.replace(early_mount, "", 1)

feature_anchor = "using Machine = jac::ComposeMachine<\n"
feature_code = r'''static esp_err_t ensureSdCardMounted() {
    // The SD mount belongs to the firmware process, not to one JavaScript
    // Machine instance. Keep a successful mount alive across Machine restarts.
    if (sd_card != nullptr) {
        return ESP_OK;
    }
    return mountSdCard();
}


template<class Next>
class SdMountFeature : public Next {
public:
    void initialize() {
        // Initialize all normal Jaculus features first, then make /sd available
        // immediately before user JavaScript/module loading proceeds.
        Next::initialize();

        const bool already_mounted = (sd_card != nullptr);
        esp_err_t sd_err = ensureSdCardMounted();
        if (sd_err == ESP_OK) {
            if (already_mounted) {
                jac::Logger::log("SD card remains mounted at /sd across Jaculus machine restart");
            }
            else {
                jac::Logger::log("SD card mounted at /sd after Jaculus machine initialization");
            }
        }
        else {
            jac::Logger::log(std::string("Late SD card mount failed: ") + esp_err_to_name(sd_err));
        }
    }
};


'''
if feature_anchor not in text:
    raise SystemExit("Could not find Machine composition anchor")
text = text.replace(feature_anchor, feature_code + feature_anchor, 1)

machine_tail = "    jac::EventLoopTerminal\n>;"
replacement_tail = "    jac::EventLoopTerminal,\n    SdMountFeature\n>;"
if machine_tail not in text:
    raise SystemExit("Could not find Machine feature tail")
text = text.replace(machine_tail, replacement_tail, 1)

main.write_text(text)
print("Applied stable late SD mount with mount persistence across Jaculus Machine restarts")
