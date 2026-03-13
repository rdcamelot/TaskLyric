#include "tasklyric/native_bridge.hpp"

#include <sstream>

namespace tasklyric::native {
namespace {

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

}  // namespace

TaskbarBridge& TaskbarBridge::instance() {
    static TaskbarBridge bridge;
    return bridge;
}

int TaskbarBridge::dispatch(std::wstring_view method, std::wstring_view payload_json) {
    std::scoped_lock lock(mutex_);
    last_method_ = std::wstring(method);

    if (method == L"tasklyric.config") {
        config_payload_ = std::wstring(payload_json);
        return 0;
    }

    if (method == L"tasklyric.update") {
        update_payload_ = std::wstring(payload_json);
        return 0;
    }

    return 1;
}

std::wstring TaskbarBridge::snapshot_json() const {
    std::scoped_lock lock(mutex_);
    std::wostringstream stream;
    stream << L"{"
           << L"\"lastMethod\":\"" << escape_json(last_method_) << L"\""
           << L",\"hasConfig\":" << (!config_payload_.empty() ? L"true" : L"false")
           << L",\"hasUpdate\":" << (!update_payload_.empty() ? L"true" : L"false")
           << L",\"configSize\":" << config_payload_.size()
           << L",\"updateSize\":" << update_payload_.size()
           << L"}";
    return stream.str();
}

}  // namespace tasklyric::native
