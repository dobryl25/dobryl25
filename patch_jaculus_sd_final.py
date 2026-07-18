from pathlib import Path

# This patch is applied after patch_jaculus_sd.py. It keeps the POSIX-backed
# Jaculus fs implementation, but corrects the SD hardware integration based on
# the Saturn/Jaculus library pin usage and the ESP-IDF v5.2.2 SDSPI example.

main = Path("firmware/main/main.cpp")
text = main.read_text()

# The user's actual Saturn application uses PMOD3 Pin1 (GPIO6) and Pin2 (GPIO8)
# as joystick ADC inputs and Pin4 (GPIO12) as the joystick button. Those pins
# therefore cannot also be used by the SD card. Move the SD card to the unused
# half of PMOD3 while keeping the display on its separate SPI2 bus:
#   PMOD3 Pin3 = GPIO47 -> CS
#   PMOD3 Pin6 = GPIO9  -> MOSI/SDI
#   PMOD3 Pin7 = GPIO11 -> MISO/SDO
#   PMOD3 Pin8 = GPIO13 -> SCK/CLK
replacements = {
    "constexpr gpio_num_t SD_CS   = GPIO_NUM_6;": "constexpr gpio_num_t SD_CS   = GPIO_NUM_47;",
    "constexpr gpio_num_t SD_MOSI = GPIO_NUM_8;": "constexpr gpio_num_t SD_MOSI = GPIO_NUM_9;",
    "constexpr gpio_num_t SD_MISO = GPIO_NUM_47;": "constexpr gpio_num_t SD_MISO = GPIO_NUM_11;",
    "constexpr gpio_num_t SD_SCK  = GPIO_NUM_12;": "constexpr gpio_num_t SD_SCK  = GPIO_NUM_13;",
    "bus_config.max_transfer_sz = 16 * 1024;": "bus_config.max_transfer_sz = 4000;",
    "spi_bus_initialize(SD_HOST, &bus_config, SPI_DMA_CH_AUTO)": "spi_bus_initialize(SD_HOST, &bus_config, SDSPI_DEFAULT_DMA)",
    "mount_config.disk_status_check_enable = true;": "mount_config.disk_status_check_enable = false;",
    'jac::Logger::log("SD card mounted at /sd (SPI <= 4 MHz, POSIX fs)");': 'jac::Logger::log("SD card mounted at /sd on dedicated SPI3 (PMOD3 pins 3/6/7/8)");',
}

for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"Expected text not found in main.cpp: {old}")
    text = text.replace(old, new, 1)

# Do not silently accept an already-initialized SPI3 bus with unknown pin
# routing. SPI3 is reserved for the SD card in this firmware; a conflict should
# fail clearly instead of attaching the SD device to a mismatched bus.
old_bus_check = '''    esp_err_t err = spi_bus_initialize(SD_HOST, &bus_config, SDSPI_DEFAULT_DMA);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }
'''
new_bus_check = '''    esp_err_t err = spi_bus_initialize(SD_HOST, &bus_config, SDSPI_DEFAULT_DMA);
    if (err != ESP_OK) {
        return err;
    }
'''
if old_bus_check not in text:
    raise SystemExit("Could not find SPI bus initialization check")
text = text.replace(old_bus_check, new_bus_check, 1)

main.write_text(text)
print("Applied final Saturn SD pin allocation and ESP-IDF SDSPI settings")
