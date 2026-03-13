#include "tasklyric/native_bridge.hpp"

#include "tasklyric/taskbar_window.hpp"

#include <algorithm>
#include <optional>
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

size_t skip_whitespace(std::wstring_view input, size_t index) {
    while (index < input.size()) {
        const wchar_t ch = input[index];
        if (ch != L' ' && ch != L'\n' && ch != L'\r' && ch != L'\t') {
            break;
        }
        index += 1;
    }
    return index;
}

int hex_value(wchar_t ch) {
    if (ch >= L'0' && ch <= L'9') {
        return ch - L'0';
    }
    if (ch >= L'a' && ch <= L'f') {
        return 10 + (ch - L'a');
    }
    if (ch >= L'A' && ch <= L'F') {
        return 10 + (ch - L'A');
    }
    return -1;
}

std::optional<std::wstring> extract_json_string(std::wstring_view input, std::wstring_view key) {
    const std::wstring pattern = L"\"" + std::wstring(key) + L"\"";
    size_t key_pos = input.find(pattern);
    if (key_pos == std::wstring_view::npos) {
        return std::nullopt;
    }

    size_t value_pos = input.find(L':', key_pos + pattern.size());
    if (value_pos == std::wstring_view::npos) {
        return std::nullopt;
    }
    value_pos = skip_whitespace(input, value_pos + 1);
    if (value_pos >= input.size() || input[value_pos] != L'"') {
        return std::nullopt;
    }

    std::wstring output;
    output.reserve(64);
    for (size_t i = value_pos + 1; i < input.size(); i += 1) {
        const wchar_t ch = input[i];
        if (ch == L'"') {
            return output;
        }
        if (ch != L'\\') {
            output.push_back(ch);
            continue;
        }
        if (i + 1 >= input.size()) {
            break;
        }
        const wchar_t next = input[++i];
        switch (next) {
        case L'"':
            output.push_back(L'"');
            break;
        case L'\\':
            output.push_back(L'\\');
            break;
        case L'/':
            output.push_back(L'/');
            break;
        case L'b':
            output.push_back(L'\b');
            break;
        case L'f':
            output.push_back(L'\f');
            break;
        case L'n':
            output.push_back(L'\n');
            break;
        case L'r':
            output.push_back(L'\r');
            break;
        case L't':
            output.push_back(L'\t');
            break;
        case L'u': {
            if (i + 4 >= input.size()) {
                return output;
            }
            int value = 0;
            for (size_t offset = 1; offset <= 4; offset += 1) {
                const int digit = hex_value(input[i + offset]);
                if (digit < 0) {
                    return output;
                }
                value = (value << 4) | digit;
            }
            output.push_back(static_cast<wchar_t>(value));
            i += 4;
            break;
        }
        default:
            output.push_back(next);
            break;
        }
    }

    return std::nullopt;
}

std::optional<int> extract_json_int(std::wstring_view input, std::wstring_view key) {
    const std::wstring pattern = L"\"" + std::wstring(key) + L"\"";
    size_t key_pos = input.find(pattern);
    if (key_pos == std::wstring_view::npos) {
        return std::nullopt;
    }

    size_t value_pos = input.find(L':', key_pos + pattern.size());
    if (value_pos == std::wstring_view::npos) {
        return std::nullopt;
    }
    value_pos = skip_whitespace(input, value_pos + 1);
    if (value_pos >= input.size()) {
        return std::nullopt;
    }

    size_t end = value_pos;
    while (end < input.size()) {
        const wchar_t ch = input[end];
        if ((ch < L'0' || ch > L'9') && ch != L'-') {
            break;
        }
        end += 1;
    }
    if (end == value_pos) {
        return std::nullopt;
    }
    return std::stoi(std::wstring(input.substr(value_pos, end - value_pos)));
}

std::optional<bool> extract_json_bool(std::wstring_view input, std::wstring_view key) {
    const std::wstring pattern = L"\"" + std::wstring(key) + L"\"";
    size_t key_pos = input.find(pattern);
    if (key_pos == std::wstring_view::npos) {
        return std::nullopt;
    }

    size_t value_pos = input.find(L':', key_pos + pattern.size());
    if (value_pos == std::wstring_view::npos) {
        return std::nullopt;
    }
    value_pos = skip_whitespace(input, value_pos + 1);
    if (input.substr(value_pos, 4) == L"true") {
        return true;
    }
    if (input.substr(value_pos, 5) == L"false") {
        return false;
    }
    return std::nullopt;
}

COLORREF parse_hex_color(std::wstring_view input, COLORREF fallback) {
    if (input.size() != 7 || input[0] != L'#') {
        return fallback;
    }
    const int r1 = hex_value(input[1]);
    const int r2 = hex_value(input[2]);
    const int g1 = hex_value(input[3]);
    const int g2 = hex_value(input[4]);
    const int b1 = hex_value(input[5]);
    const int b2 = hex_value(input[6]);
    if (std::min({r1, r2, g1, g2, b1, b2}) < 0) {
        return fallback;
    }
    const int r = (r1 << 4) | r2;
    const int g = (g1 << 4) | g2;
    const int b = (b1 << 4) | b2;
    return RGB(r, g, b);
}

TaskbarConfig parse_config_payload(std::wstring_view payload_json) {
    TaskbarConfig config;
    if (const auto value = extract_json_string(payload_json, L"fontFamily")) {
        config.font_family = *value;
    }
    if (const auto value = extract_json_int(payload_json, L"fontSize")) {
        config.font_size = std::clamp(*value, 10, 36);
    }
    if (const auto value = extract_json_string(payload_json, L"color")) {
        config.text_color = parse_hex_color(*value, config.text_color);
    }
    if (const auto value = extract_json_string(payload_json, L"subColor")) {
        config.sub_text_color = parse_hex_color(*value, config.sub_text_color);
    }
    if (const auto value = extract_json_string(payload_json, L"shadowColor")) {
        config.shadow_color = parse_hex_color(*value, config.shadow_color);
    }
    if (const auto value = extract_json_string(payload_json, L"themeMode")) {
        config.theme_mode = *value;
    }
    if (const auto value = extract_json_string(payload_json, L"align")) {
        config.align = *value;
    }
    if (const auto value = extract_json_bool(payload_json, L"debugFill")) {
        config.debug_fill = *value;
    }
    if (const auto value = extract_json_string(payload_json, L"debugFillColor")) {
        config.debug_fill_color = parse_hex_color(*value, config.debug_fill_color);
    }
    if (const auto value = extract_json_string(payload_json, L"debugBorderColor")) {
        config.debug_border_color = parse_hex_color(*value, config.debug_border_color);
    }
    if (const auto value = extract_json_int(payload_json, L"debugBorderThickness")) {
        config.debug_border_thickness = std::clamp(*value, 0, 8);
    }
    return config;
}
TaskbarLyricState parse_update_payload(std::wstring_view payload_json) {
    TaskbarLyricState state;
    if (const auto value = extract_json_string(payload_json, L"title")) {
        state.title = *value;
    }
    if (const auto value = extract_json_string(payload_json, L"artist")) {
        state.artist = *value;
    }
    if (const auto value = extract_json_string(payload_json, L"mainText")) {
        state.main_text = *value;
    }
    if (const auto value = extract_json_string(payload_json, L"subText")) {
        state.sub_text = *value;
    }
    if (const auto value = extract_json_string(payload_json, L"playbackState")) {
        state.playback_state = *value;
    }
    if (const auto value = extract_json_int(payload_json, L"progressMs")) {
        state.progress_ms = *value;
    }
    if (state.main_text.empty()) {
        state.main_text = state.title;
    }
    if (state.sub_text.empty()) {
        state.sub_text = state.artist;
    }
    return state;
}

}  // namespace

TaskbarBridge& TaskbarBridge::instance() {
    static TaskbarBridge bridge;
    return bridge;
}

int TaskbarBridge::initialize() {
    std::scoped_lock lock(mutex_);
    if (initialized_) {
        return 0;
    }
    if (!TaskbarWindow::instance().start()) {
        return 2;
    }
    initialized_ = true;
    return 0;
}

void TaskbarBridge::shutdown() {
    {
        std::scoped_lock lock(mutex_);
        if (!initialized_) {
            return;
        }
        initialized_ = false;
    }
    TaskbarWindow::instance().stop();
}

int TaskbarBridge::dispatch(std::wstring_view method, std::wstring_view payload_json) {
    if (!initialized_) {
        const int init_result = initialize();
        if (init_result != 0) {
            return init_result;
        }
    }

    {
        std::scoped_lock lock(mutex_);
        last_method_ = std::wstring(method);
        if (method == L"tasklyric.config") {
            config_payload_ = std::wstring(payload_json);
        } else if (method == L"tasklyric.update") {
            update_payload_ = std::wstring(payload_json);
        } else {
            return 1;
        }
    }

    if (method == L"tasklyric.config") {
        TaskbarWindow::instance().update_config(parse_config_payload(payload_json));
        return 0;
    }

    TaskbarWindow::instance().update_lyric(parse_update_payload(payload_json));
    return 0;
}

std::wstring TaskbarBridge::snapshot_json() const {
    std::scoped_lock lock(mutex_);
    std::wostringstream stream;
    stream << L"{"
           << L"\"initialized\":" << (initialized_ ? L"true" : L"false")
           << L",\"lastMethod\":\"" << escape_json(last_method_) << L"\""
           << L",\"hasConfig\":" << (!config_payload_.empty() ? L"true" : L"false")
           << L",\"hasUpdate\":" << (!update_payload_.empty() ? L"true" : L"false")
           << L",\"configSize\":" << config_payload_.size()
           << L",\"updateSize\":" << update_payload_.size()
           << L",\"window\":" << TaskbarWindow::instance().snapshot_json()
           << L"}";
    return stream.str();
}

}  // namespace tasklyric::native




