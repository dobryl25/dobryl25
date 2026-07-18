from pathlib import Path

main = Path("firmware/main/main.cpp")
text = main.read_text()

# Remove the boot-time SD mount. The card worked at this point in diagnostics,
# but later runtime accesses failed with EIO. Mounting as the final machine
# feature makes the SD bus/card initialization happen after all Jaculus machine
# features have initialized, immediately before user JavaScript starts.
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
feature_code = r'''static esp_err_t remountSdCard() {
    if (sd_card != nullptr) {
        esp_err_t unmount_err = esp_vfs_fat_sdcard_unmount(SD_MOUNT_POINT, sd_card);
        if (unmount_err != ESP_OK) {
            jac::Logger::log(std::string("SD card unmount before remount failed: ") + esp_err_to_name(unmount_err));
        }
        sd_card = nullptr;
    }

    return mountSdCard();
}


template<class Next>
class SdMountFeature : public Next {
public:
    void initialize() {
        // Let every normal Jaculus feature initialize first. This includes the
        // SPI feature objects and all other runtime modules.
        Next::initialize();

        esp_err_t sd_err = remountSdCard();
        if (sd_err == ESP_OK) {
            jac::Logger::log("SD card mounted at /sd after Jaculus machine initialization");
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
print("Moved Saturn SD mount to final Jaculus machine initialization stage")
