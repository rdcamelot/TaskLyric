#include "tasklyric/host_context.hpp"
#include "tasklyric/host_exports.hpp"

namespace {

constexpr const wchar_t* kEmptyWideString = L"";

std::wstring_view safe_wide(const wchar_t* value) {
    return value ? std::wstring_view(value) : std::wstring_view();
}

}  // namespace

int tasklyric_initialize(const wchar_t* base_dir) {
    return tasklyric::host::HostContext::instance().initialize(safe_wide(base_dir));
}

int tasklyric_shutdown() {
    tasklyric::host::HostContext::instance().shutdown();
    return 0;
}

int tasklyric_emit_event(const wchar_t* event_name, const wchar_t* payload_json) {
    return tasklyric::host::HostContext::instance().emit_event(
        safe_wide(event_name),
        safe_wide(payload_json)
    );
}

int tasklyric_call_native(const wchar_t* method, const wchar_t* payload_json) {
    return tasklyric::host::HostContext::instance().call_native(
        safe_wide(method),
        safe_wide(payload_json)
    );
}

const wchar_t* tasklyric_get_state_json() {
    const wchar_t* value = tasklyric::host::HostContext::instance().state_json();
    return value ? value : kEmptyWideString;
}

const wchar_t* tasklyric_get_runtime_script_path() {
    const wchar_t* value = tasklyric::host::HostContext::instance().runtime_script_path();
    return value ? value : kEmptyWideString;
}
