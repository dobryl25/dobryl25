from pathlib import Path

main = Path("firmware/main/main.cpp")
text = main.read_text()

include_anchor = '#include "esp_vfs_fat.h"\n'
includes = (
    '#include "esp_vfs_fat.h"\n'
    '#include "driver/spi_master.h"\n'
    '#include "driver/sdspi_host.h"\n'
    '#include "sdmmc_cmd.h"\n'
    '#include <cerrno>\n'
    '#include <cstdio>\n'
    '#include <cstring>\n'
    '#include <dirent.h>\n'
    '#include <sys/stat.h>\n'
)
if include_anchor not in text:
    raise SystemExit("Could not find esp_vfs_fat include anchor")
text = text.replace(include_anchor, includes, 1)

handle_anchor = 'wl_handle_t storage_wl_handle = WL_INVALID_HANDLE;\n'
sd_code = r'''wl_handle_t storage_wl_handle = WL_INVALID_HANDLE;

static constexpr const char* SD_MOUNT_POINT = "/sd";
static sdmmc_card_t* sd_card = nullptr;

static esp_err_t mountSdCard() {
    constexpr gpio_num_t SD_CS   = GPIO_NUM_6;
    constexpr gpio_num_t SD_MOSI = GPIO_NUM_8;
    constexpr gpio_num_t SD_MISO = GPIO_NUM_47;
    constexpr gpio_num_t SD_SCK  = GPIO_NUM_12;
    constexpr spi_host_device_t SD_HOST = SPI3_HOST;

    spi_bus_config_t bus_config = {};
    bus_config.mosi_io_num = SD_MOSI;
    bus_config.miso_io_num = SD_MISO;
    bus_config.sclk_io_num = SD_SCK;
    bus_config.quadwp_io_num = -1;
    bus_config.quadhd_io_num = -1;
    bus_config.max_transfer_sz = 16 * 1024;

    esp_err_t err = spi_bus_initialize(SD_HOST, &bus_config, SPI_DMA_CH_AUTO);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }

    sdmmc_host_t host = SDSPI_HOST_DEFAULT();
    host.slot = SD_HOST;
    host.max_freq_khz = 4000;

    sdspi_device_config_t slot_config = SDSPI_DEVICE_CONFIG_DEFAULT();
    slot_config.gpio_cs = SD_CS;
    slot_config.host_id = SD_HOST;

    esp_vfs_fat_mount_config_t mount_config = {};
    mount_config.format_if_mount_failed = false;
    mount_config.max_files = 10;
    mount_config.allocation_unit_size = 16 * 1024;
    mount_config.disk_status_check_enable = true;

    return esp_vfs_fat_sdspi_mount(
        SD_MOUNT_POINT,
        &host,
        &slot_config,
        &mount_config,
        &sd_card
    );
}

static void writeSdDiagnostic(esp_err_t mount_err) {
    FILE* diag = fopen("/data/sd-diagnostic.txt", "w");
    if (diag == nullptr) {
        return;
    }

    fprintf(diag, "mount_result=%s (%d)\n", esp_err_to_name(mount_err), static_cast<int>(mount_err));

    if (mount_err == ESP_OK && sd_card != nullptr) {
        fprintf(diag, "card_name=%s\n", sd_card->cid.name);
        fprintf(diag, "sector_size=%u\n", static_cast<unsigned>(sd_card->csd.sector_size));
        fprintf(diag, "capacity_sectors=%u\n", static_cast<unsigned>(sd_card->csd.capacity));

        struct stat st = {};
        errno = 0;
        int stat_result = stat("/sd", &st);
        fprintf(diag, "stat_sd=%d errno=%d (%s)\n", stat_result, errno, strerror(errno));

        errno = 0;
        DIR* dir = opendir("/sd");
        if (dir == nullptr) {
            fprintf(diag, "opendir_sd=FAIL errno=%d (%s)\n", errno, strerror(errno));
        }
        else {
            fprintf(diag, "opendir_sd=OK\n");
            int count = 0;
            while (dirent* entry = readdir(dir)) {
                fprintf(diag, "dir_entry_%d=%s\n", count, entry->d_name);
                ++count;
                if (count >= 20) {
                    break;
                }
            }
            closedir(dir);
        }

        errno = 0;
        FILE* probe = fopen("/sd/__jaculus_probe.txt", "w");
        if (probe == nullptr) {
            fprintf(diag, "fopen_write=FAIL errno=%d (%s)\n", errno, strerror(errno));
        }
        else {
            int write_result = fprintf(probe, "Jaculus SD probe\n");
            int stream_error = ferror(probe);
            int close_result = fclose(probe);
            fprintf(diag, "fopen_write=OK write_result=%d ferror=%d fclose=%d\n", write_result, stream_error, close_result);

            errno = 0;
            FILE* probe_read = fopen("/sd/__jaculus_probe.txt", "r");
            if (probe_read == nullptr) {
                fprintf(diag, "fopen_read=FAIL errno=%d (%s)\n", errno, strerror(errno));
            }
            else {
                char buffer[64] = {};
                char* read_result = fgets(buffer, sizeof(buffer), probe_read);
                int read_error = ferror(probe_read);
                int read_close = fclose(probe_read);
                fprintf(diag, "fopen_read=%s ferror=%d fclose=%d text=%s", read_result ? "OK" : "FAIL", read_error, read_close, read_result ? buffer : "<none>\n");
            }
        }
    }

    fclose(diag);
}
'''
if handle_anchor not in text:
    raise SystemExit("Could not find storage handle anchor")
text = text.replace(handle_anchor, sd_code, 1)

mount_anchor = '    ESP_ERROR_CHECK(esp_vfs_fat_spiflash_mount_rw_wl("/data", "storage", &conf, &storage_wl_handle));\n'
mount_code = r'''    ESP_ERROR_CHECK(esp_vfs_fat_spiflash_mount_rw_wl("/data", "storage", &conf, &storage_wl_handle));

    esp_err_t sd_err = mountSdCard();
    writeSdDiagnostic(sd_err);

    if (sd_err == ESP_OK) {
        jac::Logger::log("SD card mounted at /sd (SPI <= 4 MHz, diagnostics enabled)");
    }
    else {
        jac::Logger::log(std::string("SD card mount failed: ") + esp_err_to_name(sd_err));
    }
'''
if mount_anchor not in text:
    raise SystemExit("Could not find internal FAT mount anchor")
text = text.replace(mount_anchor, mount_code, 1)
main.write_text(text)

cmake = Path("firmware/main/CMakeLists.txt")
ctext = cmake.read_text()
dep_anchor = "driver pthread spiffs vfs fatfs"
if dep_anchor not in ctext:
    raise SystemExit("Could not find CMake dependency anchor")
ctext = ctext.replace(dep_anchor, "driver pthread spiffs vfs fatfs sdmmc", 1)
cmake.write_text(ctext)
