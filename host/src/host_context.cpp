#include "tasklyric/host_context.hpp"

#include "tasklyric/native_bridge.hpp"

#include <windows.h>

#include <array>
#include <chrono>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <system_error>

namespace tasklyric::host {
namespace {

using tasklyric::native::TaskbarBridge;

std::string wide_to_utf8(std::wstring_view input) {
    if (input.empty()) {
        return {};
    }

    const int size = WideCharToMultiByte(
        CP_UTF8,
        0,
        input.data(),
        static_cast<int>(input.size()),
        nullptr,
        0,
        nullptr,
        nullptr
    );
    if (size <= 0) {
        return {};
    }

    std::string output(size, '\0');
    WideCharToMultiByte(
        CP_UTF8,
        0,
        input.data(),
        static_cast<int>(input.size()),
        output.data(),
        size,
        nullptr,
        nullptr
    );
    return output;
}

std::wstring escape_json(std::wstring_view input) {
    std::wstring output;
    output.reserve(input.size() + 8);
    for (const wchar_t ch : input) {
        switch (ch) {
        case L'\\':
            output += L"\\\\";
            break;
        case L'"':
            output += L"\\\"";
            break;
        case L'\n':
            output += L"\\n";
            break;
        case L'\r':
            output += L"\\r";
            break;
        case L'\t':
            output += L"\\t";
            break;
        default:
            output.push_back(ch);
            break;
        }
    }
    return output;
}

std::wstring current_timestamp() {
    using clock = std::chrono::system_clock;
    const auto now = clock::now();
    const std::time_t seconds = clock::to_time_t(now);

    std::tm local_time{};
    localtime_s(&local_time, &seconds);

    std::wostringstream stream;
    stream << std::put_time(&local_time, L"%Y-%m-%d %H:%M:%S");
    return stream.str();
}

std::filesystem::path current_working_directory() {
    std::array<wchar_t, MAX_PATH> buffer{};
    const DWORD result = GetCurrentDirectoryW(static_cast<DWORD>(buffer.size()), buffer.data());
    if (result == 0 || result >= buffer.size()) {
        return std::filesystem::current_path();
    }
    return std::filesystem::path(buffer.data());
}

}  // namespace

HostContext& HostContext::instance() {
    static HostContext context;
    return context;
}

int HostContext::initialize(std::wstring_view base_dir) {
    std::scoped_lock lock(mutex_);
    if (initialized_) {
        return 0;
    }

    base_dir_ = resolve_base_dir(base_dir);
    runtime_script_path_ = base_dir_ / L"runtime" / L"tasklyric.runtime.js";
    logs_dir_ = base_dir_ / L"logs";
    state_dir_ = base_dir_ / L"state";
    config_dir_ = base_dir_ / L"config";
    log_path_ = logs_dir_ / L"tasklyric-host.log";
    config_path_ = config_dir_ / L"tasklyric.config.json";
    last_event_path_ = state_dir_ / L"last-event.json";
    last_native_update_path_ = state_dir_ / L"last-native-update.json";

    std::error_code ec;
    std::filesystem::create_directories(logs_dir_, ec);
    if (ec) {
        return 10;
    }
    std::filesystem::create_directories(state_dir_, ec);
    if (ec) {
        return 11;
    }
    std::filesystem::create_directories(config_dir_, ec);
    if (ec) {
        return 12;
    }

    initialized_ = true;
    log_line(L"TaskLyric host initialized");
    rebuild_state_json();
    return 0;
}

void HostContext::shutdown() {
    std::scoped_lock lock(mutex_);
    if (!initialized_) {
        return;
    }

    log_line(L"TaskLyric host shutdown");
    initialized_ = false;
    rebuild_state_json();
}

int HostContext::emit_event(std::wstring_view event_name, std::wstring_view payload_json) {
    std::scoped_lock lock(mutex_);
    if (!initialized_) {
        return 20;
    }

    last_event_name_ = std::wstring(event_name);
    last_event_payload_ = std::wstring(payload_json);
    write_utf8_file(last_event_path_, payload_json);
    log_line(L"event: " + std::wstring(event_name));
    rebuild_state_json();
    return 0;
}

int HostContext::call_native(std::wstring_view method, std::wstring_view payload_json) {
    std::scoped_lock lock(mutex_);
    if (!initialized_) {
        return 21;
    }

    if (method == L"tasklyric.config") {
        write_utf8_file(config_path_, payload_json);
    } else if (method == L"tasklyric.update") {
        write_utf8_file(last_native_update_path_, payload_json);
    }

    const int result = TaskbarBridge::instance().dispatch(method, payload_json);
    log_line(L"native: " + std::wstring(method));
    rebuild_state_json();
    return result;
}

const wchar_t* HostContext::state_json() {
    std::scoped_lock lock(mutex_);
    rebuild_state_json();
    return state_json_cache_.c_str();
}

const wchar_t* HostContext::runtime_script_path() {
    std::scoped_lock lock(mutex_);
    state_json_cache_ = runtime_script_path_.wstring();
    return state_json_cache_.c_str();
}

std::filesystem::path HostContext::resolve_base_dir(std::wstring_view base_dir) const {
    if (!base_dir.empty()) {
        return std::filesystem::path(base_dir);
    }
    return current_working_directory();
}

void HostContext::rebuild_state_json() {
    std::wostringstream stream;
    stream << L"{"
           << L"\"initialized\":" << (initialized_ ? L"true" : L"false")
           << L",\"baseDir\":\"" << escape_json(base_dir_.wstring()) << L"\""
           << L",\"runtimeScriptPath\":\"" << escape_json(runtime_script_path_.wstring()) << L"\""
           << L",\"lastEventName\":\"" << escape_json(last_event_name_) << L"\""
           << L",\"lastEventPayloadSize\":" << last_event_payload_.size()
           << L",\"nativeBridge\":" << TaskbarBridge::instance().snapshot_json()
           << L"}";
    state_json_cache_ = stream.str();
}

void HostContext::log_line(std::wstring_view line) {
    const std::wstring formatted = current_timestamp() + L" " + std::wstring(line) + L"\n";
    const std::string utf8 = wide_to_utf8(formatted);

    std::ofstream stream(log_path_, std::ios::app | std::ios::binary);
    stream.write(utf8.data(), static_cast<std::streamsize>(utf8.size()));
    OutputDebugStringW(formatted.c_str());
}

void HostContext::write_utf8_file(const std::filesystem::path& path, std::wstring_view content) {
    const std::string utf8 = wide_to_utf8(content);
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream.write(utf8.data(), static_cast<std::streamsize>(utf8.size()));
}

}  // namespace tasklyric::host
