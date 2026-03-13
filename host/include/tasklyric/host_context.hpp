#pragma once

#include <filesystem>
#include <mutex>
#include <string>
#include <string_view>

namespace tasklyric::host {

class HostContext {
public:
    static HostContext& instance();

    int initialize(std::wstring_view base_dir);
    void shutdown();

    int emit_event(std::wstring_view event_name, std::wstring_view payload_json);
    int call_native(std::wstring_view method, std::wstring_view payload_json);

    const wchar_t* state_json();
    const wchar_t* runtime_script_path();
    const wchar_t* take_pending_command_json();

private:
    HostContext() = default;

    std::filesystem::path resolve_base_dir(std::wstring_view base_dir) const;
    void rebuild_state_json();
    void log_line(std::wstring_view line);
    void write_utf8_file(const std::filesystem::path& path, std::wstring_view content);

    std::mutex mutex_;
    bool initialized_ = false;
    std::filesystem::path base_dir_;
    std::filesystem::path runtime_script_path_;
    std::filesystem::path logs_dir_;
    std::filesystem::path state_dir_;
    std::filesystem::path config_dir_;
    std::filesystem::path log_path_;
    std::filesystem::path config_path_;
    std::filesystem::path last_event_path_;
    std::filesystem::path last_native_update_path_;
    std::wstring last_event_name_;
    std::wstring last_event_payload_;
    std::wstring pending_command_cache_;
    std::wstring state_json_cache_;
};

}  // namespace tasklyric::host
