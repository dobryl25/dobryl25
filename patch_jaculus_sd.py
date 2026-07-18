from pathlib import Path

# -----------------------------------------------------------------------------
# Patch Jaculus-esp32 main firmware to mount the Saturn microSD card at /sd.
# -----------------------------------------------------------------------------
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
'''
if handle_anchor not in text:
    raise SystemExit("Could not find storage handle anchor")
text = text.replace(handle_anchor, sd_code, 1)

mount_anchor = '    ESP_ERROR_CHECK(esp_vfs_fat_spiflash_mount_rw_wl("/data", "storage", &conf, &storage_wl_handle));\n'
mount_code = r'''    ESP_ERROR_CHECK(esp_vfs_fat_spiflash_mount_rw_wl("/data", "storage", &conf, &storage_wl_handle));

    esp_err_t sd_err = mountSdCard();
    if (sd_err == ESP_OK) {
        jac::Logger::log("SD card mounted at /sd (SPI <= 4 MHz, POSIX fs)");
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

# -----------------------------------------------------------------------------
# Replace Jaculus-machine's std::fstream/std::filesystem-backed runtime file
# operations with POSIX/C stdio calls. ESP-IDF's VFS supports these calls for
# both the internal FAT mount and the external SDSPI FAT mount.
# -----------------------------------------------------------------------------
file_h = Path("firmware/components/jac-machine/jac/features/types/file.h")
if not file_h.exists():
    raise SystemExit(f"Local jac-machine component not found: {file_h}")

file_h.write_text(r'''#pragma once

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <string>
#include <utility>

#include <jac/machine/values.h>

namespace jac {


class File {
    FILE* _file = nullptr;
public:
    std::string path_;

    File(std::string path, std::string flags): path_(std::move(path)) {
        const bool read = flags.find('r') != std::string::npos;
        const bool write = flags.find('w') != std::string::npos;
        const bool append = flags.find('a') != std::string::npos;
        const bool binary = flags.find('b') != std::string::npos;

        std::string mode;
        if (append) {
            mode = read || write ? "a+" : "a";
        }
        else if (write) {
            mode = read ? "w+" : "w";
        }
        else if (read) {
            mode = "r";
        }
        else {
            throw jac::Exception::create(jac::Exception::Type::Error, "Invalid file flags");
        }

        if (binary) {
            mode += "b";
        }

        errno = 0;
        _file = std::fopen(path_.c_str(), mode.c_str());
        if (_file == nullptr) {
            throw jac::Exception::create(
                jac::Exception::Type::Error,
                "Could not open file: " + path_ + ": " + std::strerror(errno)
            );
        }
    }

    File(std::filesystem::path path, std::string flags): File(path.string(), std::move(flags)) {}

    File(const File&) = delete;
    File& operator=(const File&) = delete;

    File(File&& other) noexcept:
        _file(other._file), path_(std::move(other.path_)) {
        other._file = nullptr;
    }

    File& operator=(File&& other) noexcept {
        if (this != &other) {
            close();
            _file = other._file;
            path_ = std::move(other.path_);
            other._file = nullptr;
        }
        return *this;
    }

    std::string read(int length = 1024) {
        if (_file == nullptr || length <= 0) {
            return {};
        }

        std::string buffer(static_cast<size_t>(length), '\0');
        const size_t count = std::fread(buffer.data(), 1, buffer.size(), _file);
        if (std::ferror(_file)) {
            throw jac::Exception::create(
                jac::Exception::Type::Error,
                "Could not read file: " + path_
            );
        }
        buffer.resize(count);
        return buffer;
    }

    void write(std::string data) {
        if (_file == nullptr) {
            throw jac::Exception::create(jac::Exception::Type::Error, "File is closed: " + path_);
        }

        const size_t written = std::fwrite(data.data(), 1, data.size(), _file);
        if (written != data.size()) {
            throw jac::Exception::create(
                jac::Exception::Type::Error,
                "Could not write file: " + path_
            );
        }
    }

    bool isOpen() {
        return _file != nullptr;
    }

    void close() {
        if (_file != nullptr) {
            std::fclose(_file);
            _file = nullptr;
        }
    }

    ~File() {
        close();
    }
};


} // namespace jac
''')

filesystem_h = Path("firmware/components/jac-machine/jac/features/filesystemFeature.h")
if not filesystem_h.exists():
    raise SystemExit(f"Local jac-machine component not found: {filesystem_h}")

filesystem_h.write_text(r'''#pragma once

#include <jac/machine/class.h>
#include <jac/machine/functionFactory.h>
#include <jac/machine/machine.h>

#include <cerrno>
#include <cstring>
#include <dirent.h>
#include <filesystem>
#include <noal_func.h>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

#include "types/file.h"

// XXX: automatic path normalization is performed because esp-idf does not support "." and ".." in paths


namespace jac {


struct FileProtoBuilder : public ProtoBuilder::Opaque<File>, public ProtoBuilder::Properties {
    static void addProperties(ContextRef ctx, Object proto) {
        addPropMember<std::string, &File::path_>(ctx, proto, "path", PropFlags::Enumerable);
        addMethodMember<bool(File::*)(), &File::isOpen>(ctx, proto, "isOpen", PropFlags::Enumerable);
        addMethodMember<void(File::*)(), &File::close>(ctx, proto, "close", PropFlags::Enumerable);
        addMethodMember<std::string(File::*)(int), &File::read>(ctx, proto, "read", PropFlags::Enumerable);
        addMethodMember<void(File::*)(std::string), &File::write>(ctx, proto, "write", PropFlags::Enumerable);
    }
};


template<class Next>
class FilesystemFeature : public Next {
private:

    std::filesystem::path _codeDir = ".";
    std::filesystem::path _workingDir = ".";

public:
    using FileClass = Class<FileProtoBuilder>;

    void setCodeDir(std::string path_) {
        this->_codeDir = std::filesystem::path(path_).lexically_normal();
    }

    void setWorkingDir(std::string path_) {
        this->_workingDir = std::filesystem::path(path_).lexically_normal();
    }

    class Path {
        FilesystemFeature& _feature;
    public:
        Path(FilesystemFeature& feature): _feature(feature) {}

        std::string normalize(std::string path_) {
            return std::filesystem::path(path_).lexically_normal().string();
        }

        std::string dirname(std::string path_) {
            auto res = std::filesystem::path(path_).parent_path().string();
            return res.empty() ? "." : res;
        }

        std::string basename(std::string path_) {
            return std::filesystem::path(path_).filename().string();
        }

        std::string join(std::vector<std::string> paths) {
            std::filesystem::path path_;
            for (auto& p : paths) {
                path_ /= p;
            }
            return path_.string();
        }
    };

private:
    class Fs {
        FilesystemFeature& _feature;

        static void throwFsError(const std::string& operation, const std::string& path_) {
            throw jac::Exception::create(
                jac::Exception::Type::Error,
                operation + ": " + path_ + ": " + std::strerror(errno)
            );
        }

        static bool statPath(const std::string& path_, struct stat& st) {
            errno = 0;
            if (::stat(path_.c_str(), &st) == 0) {
                return true;
            }
            if (errno == ENOENT) {
                return false;
            }
            throwFsError("Could not stat path", path_);
            return false;
        }

        static void mkdirRecursive(const std::string& path_) {
            std::filesystem::path normalized(path_);
            std::filesystem::path current;

            for (const auto& part : normalized) {
                current /= part;
                const std::string currentPath = current.string();
                if (currentPath.empty() || currentPath == "/") {
                    continue;
                }

                struct stat st = {};
                errno = 0;
                if (::stat(currentPath.c_str(), &st) == 0) {
                    if (!S_ISDIR(st.st_mode)) {
                        errno = ENOTDIR;
                        throwFsError("Path component is not a directory", currentPath);
                    }
                    continue;
                }

                if (errno != ENOENT) {
                    throwFsError("Could not stat directory", currentPath);
                }

                errno = 0;
                if (::mkdir(currentPath.c_str(), 0777) != 0 && errno != EEXIST) {
                    throwFsError("Could not create directory", currentPath);
                }
            }
        }

        static void removeRecursive(const std::string& path_) {
            struct stat st = {};
            errno = 0;
            if (::stat(path_.c_str(), &st) != 0) {
                if (errno == ENOENT) {
                    return;
                }
                throwFsError("Could not stat path", path_);
            }

            if (!S_ISDIR(st.st_mode)) {
                errno = 0;
                if (::remove(path_.c_str()) != 0 && errno != ENOENT) {
                    throwFsError("Could not remove file", path_);
                }
                return;
            }

            errno = 0;
            DIR* dir = ::opendir(path_.c_str());
            if (dir == nullptr) {
                throwFsError("Could not open directory", path_);
            }

            while (dirent* entry = ::readdir(dir)) {
                const std::string name = entry->d_name;
                if (name == "." || name == "..") {
                    continue;
                }

                std::string child = path_;
                if (!child.empty() && child.back() != '/') {
                    child += '/';
                }
                child += name;
                removeRecursive(child);
            }
            ::closedir(dir);

            errno = 0;
            if (::rmdir(path_.c_str()) != 0 && errno != ENOENT) {
                throwFsError("Could not remove directory", path_);
            }
        }

        std::string workingPath(std::string path_) {
            return _feature.path.normalize((_feature._workingDir / path_).string());
        }

        std::string codePath(std::string path_) {
            return _feature.path.normalize((_feature._codeDir / path_).string());
        }

    public:
        Fs(FilesystemFeature& feature) : _feature(feature) {}

        std::string loadCode(std::string filename) {
            std::string buffer;
            File file(codePath(filename), "r");
            std::string read = file.read();
            while (!read.empty()) {
                buffer += read;
                read = file.read();
            }
            return buffer;
        }

        bool existsCode(std::string path_) {
            struct stat st = {};
            return statPath(codePath(path_), st);
        }

        bool isFileCode(std::string path_) {
            struct stat st = {};
            return statPath(codePath(path_), st) && S_ISREG(st.st_mode);
        }

        bool isDirectoryCode(std::string path_) {
            struct stat st = {};
            return statPath(codePath(path_), st) && S_ISDIR(st.st_mode);
        }

        File open(std::string path_, std::string flags) {
            return File(workingPath(path_), std::move(flags));
        }

        bool exists(std::string path_) {
            struct stat st = {};
            return statPath(workingPath(path_), st);
        }

        bool isFile(std::string path_) {
            struct stat st = {};
            return statPath(workingPath(path_), st) && S_ISREG(st.st_mode);
        }

        bool isDirectory(std::string path_) {
            struct stat st = {};
            return statPath(workingPath(path_), st) && S_ISDIR(st.st_mode);
        }

        void mkdir(std::string path_) {
            mkdirRecursive(workingPath(path_));
        }

        std::vector<std::string> readdir(std::string path_) {
            const std::string resolved = workingPath(path_);
            std::vector<std::string> res;

            errno = 0;
            DIR* dir = ::opendir(resolved.c_str());
            if (dir == nullptr) {
                throwFsError("Could not open directory", resolved);
            }

            while (dirent* entry = ::readdir(dir)) {
                const std::string name = entry->d_name;
                if (name != "." && name != "..") {
                    res.push_back(name);
                }
            }
            ::closedir(dir);
            return res;
        }

        void rm(std::string path_) {
            const std::string resolved = workingPath(path_);
            errno = 0;
            if (::remove(resolved.c_str()) != 0 && errno != ENOENT) {
                throwFsError("Could not remove path", resolved);
            }
        }

        void rmdir(std::string path_) {
            removeRecursive(workingPath(path_));
        }
    };

public:
    Path path;
    Fs fs;

    FilesystemFeature() : path(*this), fs(*this) {
        FileClass::init("File");
    }

    void initialize() {
        Next::initialize();

        FileClass::initContext(this->context());

        FunctionFactory ff(this->context());

        Module& pathMod = this->newModule("path");
        pathMod.addExport("normalize", ff.newFunction(noal::function(&Path::normalize, &(this->path))));
        pathMod.addExport("dirname", ff.newFunction(noal::function(&Path::dirname, &(this->path))));
        pathMod.addExport("basename", ff.newFunction(noal::function(&Path::basename, &(this->path))));
        pathMod.addExport("join", ff.newFunctionVariadic([this](std::vector<ValueWeak> paths) {
            std::vector<std::string> paths_;
            for (auto& p : paths) {
                paths_.push_back(p.to<std::string>());
            }
            return this->path.join(paths_);
        }));

        Module& fsMod = this->newModule("fs");
        fsMod.addExport("open", ff.newFunction([this](std::string path_, std::string flags) {
            return FileClass::createInstance(this->context(), new File(this->fs.open(path_, flags)));
        }));
        fsMod.addExport("exists", ff.newFunction(noal::function(&Fs::exists, &(this->fs))));
        fsMod.addExport("isFile", ff.newFunction(noal::function(&Fs::isFile, &(this->fs))));
        fsMod.addExport("isDirectory", ff.newFunction(noal::function(&Fs::isDirectory, &(this->fs))));
        fsMod.addExport("mkdir", ff.newFunction(noal::function(&Fs::mkdir, &(this->fs))));
        fsMod.addExport("rm", ff.newFunction(noal::function(&Fs::rm, &(this->fs))));
        fsMod.addExport("rmdir", ff.newFunction(noal::function(&Fs::rmdir, &(this->fs))));
        fsMod.addExport("readdir", ff.newFunction(noal::function(&Fs::readdir, &(this->fs))));
    }
};


} // namespace jac
''')

print("Patched Jaculus Saturn SD support and POSIX filesystem backend")
