from pathlib import Path

main = Path("firmware/main/main.cpp")
text = main.read_text()

include_anchor = '#include "esp_vfs_fat.h"\n'
includes = (
    '#include "esp_vfs_fat.h"\n'
    '#include "driver/spi_master.h"\n'
    '#include "driver/sdspi_host.h"\n'
    '#include "sdmmc_cmd.h"\n'
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

    // The default SDSPI speed is 20 MHz. With Dupont jumper wires this can be
    // unreliable, so limit normal card transfers to 4 MHz.
    host.max_freq_khz = 4000;

    sdspi_device_config_t slot_config = SDSPI_DEVICE_CONFIG_DEFAULT();
    slot_config.gpio_cs = SD_CS;
    slot_config.host_id = SD_HOST;

    esp_vfs_fat_mount_config_t mount_config = {};
    mount_config.format_if_mount_failed = false;
    mount_config.max_files = 10;
    mount_config.allocation_unit_size = 16 * 1024;

    return esp_vfs_fat_sdspi_mount(
        SD_MOUNT_POINT,
        &host,
        &slot_config,
        &mount_config,
        &sd_card
    );
}
'''
if handle_anchor not in text:
    raise SystemExit("Could not find storage handle anchor")
text = text.replace(handle_anchor, sd_code, 1)

mount_anchor = '    ESP_ERROR_CHECK(esp_vfs_fat_spiflash_mount_rw_wl("/data", "storage", &conf, &storage_wl_handle));\n'
mount_code = r'''    ESP_ERROR_CHECK(esp_vfs_fat_spiflash_mount_rw_wl("/data", "storage", &conf, &storage_wl_handle));

    esp_err_t sd_err = mountSdCard();
    if (sd_err == ESP_OK) {
        jac::Logger::log("SD card mounted at /sd (SPI <= 4 MHz)");
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
