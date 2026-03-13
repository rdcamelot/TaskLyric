#pragma once

#include <mutex>
#include <string>
#include <string_view>

namespace tasklyric::native {

class TaskbarBridge {
public:
    static TaskbarBridge& instance();

    int dispatch(std::wstring_view method, std::wstring_view payload_json);
    std::wstring snapshot_json() const;

private:
    TaskbarBridge() = default;

    mutable std::mutex mutex_;
    std::wstring last_method_;
    std::wstring config_payload_;
    std::wstring update_payload_;
};

}  // namespace tasklyric::native
