#include "tasklyric/taskbar_locator.hpp"

#include <windows.h>
#include <oleauto.h>
#include <uiautomation.h>

#include <algorithm>
#include <string>

namespace tasklyric::native {
namespace {

constexpr wchar_t kExplorerAdvancedKey[] = L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced";
constexpr wchar_t kTaskbarAlignmentValue[] = L"TaskbarAl";
constexpr wchar_t kWidgetsValue[] = L"TaskbarDa";
constexpr int kPreferredWidth = 560;
constexpr int kMinimumWidth = 220;
constexpr int kOuterMargin = 12;
constexpr int kAnchorGap = 6;

using UiaElement = IUIAutomationElement;
using UiaCondition = IUIAutomationCondition;
using UiaArray = IUIAutomationElementArray;

struct AutoVariant {
    VARIANT value{};

    AutoVariant() {
        VariantInit(&value);
    }

    ~AutoVariant() {
        VariantClear(&value);
    }
};

template <typename T>
void safe_release(T*& pointer) {
    if (pointer) {
        pointer->Release();
        pointer = nullptr;
    }
}

bool is_valid_rect(const RECT& rect) {
    return rect.right > rect.left && rect.bottom > rect.top;
}

RECT empty_rect() {
    RECT rect{};
    return rect;
}

RECT union_rect(const RECT& left, const RECT& right) {
    if (!is_valid_rect(left)) {
        return right;
    }
    if (!is_valid_rect(right)) {
        return left;
    }
    RECT merged{};
    merged.left = std::min(left.left, right.left);
    merged.top = std::min(left.top, right.top);
    merged.right = std::max(left.right, right.right);
    merged.bottom = std::max(left.bottom, right.bottom);
    return merged;
}

bool query_registry_dword(const wchar_t* value_name, DWORD* out_value) {
    if (!out_value) {
        return false;
    }

    HKEY key = nullptr;
    const LONG open_result = RegOpenKeyExW(HKEY_CURRENT_USER, kExplorerAdvancedKey, 0, KEY_QUERY_VALUE, &key);
    if (open_result != ERROR_SUCCESS) {
        return false;
    }

    DWORD type = 0;
    DWORD size = sizeof(DWORD);
    DWORD value = 0;
    const LONG query_result = RegQueryValueExW(key, value_name, nullptr, &type, reinterpret_cast<LPBYTE>(&value), &size);
    RegCloseKey(key);
    if (query_result != ERROR_SUCCESS || type != REG_DWORD) {
        return false;
    }

    *out_value = value;
    return true;
}

bool create_string_condition(IUIAutomation* automation, PROPERTYID property_id, const wchar_t* value, UiaCondition** out_condition) {
    if (!automation || !value || !out_condition) {
        return false;
    }

    AutoVariant variant;
    variant.value.vt = VT_BSTR;
    variant.value.bstrVal = SysAllocString(value);
    if (!variant.value.bstrVal) {
        return false;
    }

    return SUCCEEDED(automation->CreatePropertyCondition(property_id, variant.value, out_condition));
}

bool element_rect(UiaElement* element, RECT* out_rect) {
    if (!element || !out_rect) {
        return false;
    }

    RECT rect{};
    if (FAILED(element->get_CurrentBoundingRectangle(&rect)) || !is_valid_rect(rect)) {
        return false;
    }

    *out_rect = rect;
    return true;
}

bool find_first_descendant(IUIAutomation* automation, UiaElement* root, PROPERTYID property_id, const wchar_t* value, UiaElement** out_element) {
    if (!automation || !root || !out_element) {
        return false;
    }

    UiaCondition* condition = nullptr;
    if (!create_string_condition(automation, property_id, value, &condition)) {
        return false;
    }

    UiaElement* element = nullptr;
    const HRESULT hr = root->FindFirst(TreeScope_Descendants, condition, &element);
    safe_release(condition);
    if (FAILED(hr) || !element) {
        return false;
    }

    *out_element = element;
    return true;
}

bool find_all_descendants(IUIAutomation* automation, UiaElement* root, PROPERTYID property_id, const wchar_t* value, UiaArray** out_array) {
    if (!automation || !root || !out_array) {
        return false;
    }

    UiaCondition* condition = nullptr;
    if (!create_string_condition(automation, property_id, value, &condition)) {
        return false;
    }

    UiaArray* array = nullptr;
    const HRESULT hr = root->FindAll(TreeScope_Descendants, condition, &array);
    safe_release(condition);
    if (FAILED(hr) || !array) {
        return false;
    }

    *out_array = array;
    return true;
}

RECT union_array_bounds(UiaArray* array) {
    if (!array) {
        return empty_rect();
    }

    int length = 0;
    if (FAILED(array->get_Length(&length)) || length <= 0) {
        return empty_rect();
    }

    RECT merged{};
    bool has_rect = false;
    for (int index = 0; index < length; index += 1) {
        UiaElement* element = nullptr;
        if (FAILED(array->GetElement(index, &element)) || !element) {
            continue;
        }

        RECT rect{};
        const bool valid = element_rect(element, &rect);
        safe_release(element);
        if (!valid) {
            continue;
        }

        merged = has_rect ? union_rect(merged, rect) : rect;
        has_rect = true;
    }

    return has_rect ? merged : empty_rect();
}

RECT hwnd_rect(HWND hwnd) {
    RECT rect{};
    if (!hwnd || !GetWindowRect(hwnd, &rect)) {
        return empty_rect();
    }
    return rect;
}

RECT compute_left_of_anchor_rect(const RECT& frame, const RECT& anchor, const RECT& widgets) {
    if (!is_valid_rect(frame) || !is_valid_rect(anchor)) {
        return empty_rect();
    }

    const int left_boundary = is_valid_rect(widgets) ? widgets.right : frame.left;
    const int right_boundary = anchor.left;
    const int available = right_boundary - left_boundary - kAnchorGap;
    if (available < kMinimumWidth) {
        return empty_rect();
    }

    const int width = std::min(kPreferredWidth, available - (kOuterMargin * 2));
    if (width < kMinimumWidth) {
        return empty_rect();
    }

    RECT rect{};
    rect.left = std::max(left_boundary + kOuterMargin, right_boundary - kAnchorGap - width);
    rect.top = frame.top;
    rect.right = rect.left + width;
    rect.bottom = frame.bottom;
    return rect;
}

RECT compute_between_rect(const RECT& frame, const RECT& left_anchor, const RECT& right_anchor) {
    if (!is_valid_rect(frame)) {
        return empty_rect();
    }

    const int left_boundary = is_valid_rect(left_anchor) ? left_anchor.right : frame.left;
    const int right_boundary = is_valid_rect(right_anchor) ? right_anchor.left : frame.right;
    const int available = right_boundary - left_boundary - (kOuterMargin * 2);
    if (available < kMinimumWidth) {
        return empty_rect();
    }

    const int width = std::min(kPreferredWidth, available);
    RECT rect{};
    rect.left = left_boundary + std::max(kOuterMargin, (available - width) / 2);
    rect.top = frame.top;
    rect.right = rect.left + width;
    rect.bottom = frame.bottom;
    return rect;
}

RECT fallback_task_list_rect(HWND taskbar_hwnd) {
    RECT rect = hwnd_rect(FindWindowExW(taskbar_hwnd, nullptr, L"Start", nullptr));
    RECT task_switcher = hwnd_rect(FindWindowExW(taskbar_hwnd, nullptr, L"MSTaskSwWClass", nullptr));
    rect = union_rect(rect, task_switcher);
    RECT rebar = hwnd_rect(FindWindowExW(taskbar_hwnd, nullptr, L"ReBarWindow32", nullptr));
    rect = union_rect(rect, rebar);
    return rect;
}

}  // namespace

struct TaskbarLocator::Impl {
    HWND taskbar_hwnd = nullptr;
    IUIAutomation* automation = nullptr;

    ~Impl() {
        safe_release(automation);
    }
};

TaskbarLocator::~TaskbarLocator() {
    shutdown();
}

bool TaskbarLocator::initialize(HWND taskbar_hwnd) {
    shutdown();

    if (!taskbar_hwnd || !IsWindow(taskbar_hwnd)) {
        return false;
    }

    Impl* impl = new Impl();
    impl->taskbar_hwnd = taskbar_hwnd;
    const HRESULT hr = CoCreateInstance(CLSID_CUIAutomation, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&impl->automation));
    if (FAILED(hr) || !impl->automation) {
        delete impl;
        return false;
    }

    impl_ = impl;
    return true;
}

TaskbarLayout TaskbarLocator::query() {
    TaskbarLayout layout;
    if (!impl_ || !impl_->taskbar_hwnd || !IsWindow(impl_->taskbar_hwnd) || !impl_->automation) {
        layout.source = L"locator-unavailable";
        return layout;
    }

    DWORD alignment = 1;
    DWORD widgets = 0;
    const bool has_alignment = query_registry_dword(kTaskbarAlignmentValue, &alignment);
    const bool has_widgets = query_registry_dword(kWidgetsValue, &widgets);
    layout.centered = !has_alignment || alignment != 0;
    layout.widgets_enabled = has_widgets && widgets != 0;

    HWND automation_host = FindWindowExW(impl_->taskbar_hwnd, nullptr, L"Windows.UI.Input.InputSite.WindowClass", nullptr);
    if (!automation_host) {
        automation_host = FindWindowExW(impl_->taskbar_hwnd, nullptr, L"Windows.UI.Composition.DesktopWindowContentBridge", nullptr);
    }
    if (!automation_host) {
        automation_host = impl_->taskbar_hwnd;
    }

    UiaElement* root = nullptr;
    if (FAILED(impl_->automation->ElementFromHandle(automation_host, &root)) || !root) {
        layout.taskbar_frame = hwnd_rect(impl_->taskbar_hwnd);
        layout.task_list = fallback_task_list_rect(impl_->taskbar_hwnd);
        layout.tray_frame = hwnd_rect(FindWindowExW(impl_->taskbar_hwnd, nullptr, L"TrayNotifyWnd", nullptr));
        layout.lyric_rect = compute_left_of_anchor_rect(layout.taskbar_frame, layout.task_list, empty_rect());
        layout.valid = is_valid_rect(layout.lyric_rect);
        layout.source = layout.valid ? L"window-fallback" : L"window-fallback-empty";
        return layout;
    }

    UiaElement* taskbar_frame = nullptr;
    UiaElement* start_button = nullptr;
    UiaElement* widgets_button = nullptr;
    UiaArray* task_buttons = nullptr;
    UiaArray* tray_icons = nullptr;

    find_first_descendant(impl_->automation, root, UIA_AutomationIdPropertyId, L"TaskbarFrame", &taskbar_frame);
    find_first_descendant(impl_->automation, root, UIA_AutomationIdPropertyId, L"StartButton", &start_button);
    find_first_descendant(impl_->automation, root, UIA_AutomationIdPropertyId, L"WidgetsButton", &widgets_button);
    find_all_descendants(impl_->automation, root, UIA_AutomationIdPropertyId, L"Taskbar.TaskListButtonAutomationPeer", &task_buttons);
    find_all_descendants(impl_->automation, root, UIA_AutomationIdPropertyId, L"SystemTrayIcon", &tray_icons);

    RECT taskbar_frame_rect = empty_rect();
    RECT start_rect = empty_rect();
    RECT widgets_rect = empty_rect();
    RECT task_buttons_rect = union_array_bounds(task_buttons);
    RECT tray_icons_rect = union_array_bounds(tray_icons);

    element_rect(taskbar_frame, &taskbar_frame_rect);
    element_rect(start_button, &start_rect);
    element_rect(widgets_button, &widgets_rect);

    if (!is_valid_rect(taskbar_frame_rect)) {
        taskbar_frame_rect = hwnd_rect(impl_->taskbar_hwnd);
    }
    if (!is_valid_rect(task_buttons_rect)) {
        task_buttons_rect = fallback_task_list_rect(impl_->taskbar_hwnd);
    }
    if (!is_valid_rect(tray_icons_rect)) {
        tray_icons_rect = hwnd_rect(FindWindowExW(impl_->taskbar_hwnd, nullptr, L"TrayNotifyWnd", nullptr));
    }

    layout.taskbar_frame = taskbar_frame_rect;
    layout.task_list = union_rect(start_rect, task_buttons_rect);
    layout.tray_frame = tray_icons_rect;
    layout.widgets_button = widgets_rect;

    if (layout.centered) {
        layout.lyric_rect = compute_left_of_anchor_rect(layout.taskbar_frame, layout.task_list, layout.widgets_enabled ? layout.widgets_button : empty_rect());
        layout.source = is_valid_rect(layout.lyric_rect) ? L"uia-left-of-start" : L"uia-left-of-start-empty";
    }

    if (!is_valid_rect(layout.lyric_rect)) {
        layout.lyric_rect = compute_between_rect(layout.taskbar_frame, layout.task_list, layout.tray_frame);
        if (is_valid_rect(layout.lyric_rect)) {
            layout.source = L"uia-between-tasklist-tray";
        }
    }

    if (!is_valid_rect(layout.lyric_rect)) {
        layout.lyric_rect = compute_left_of_anchor_rect(layout.taskbar_frame, layout.task_list, empty_rect());
        if (is_valid_rect(layout.lyric_rect)) {
            layout.source = L"uia-anchor-fallback";
        }
    }

    layout.valid = is_valid_rect(layout.lyric_rect);
    if (!layout.valid && layout.source.empty()) {
        layout.source = L"uia-empty";
    }

    safe_release(tray_icons);
    safe_release(task_buttons);
    safe_release(widgets_button);
    safe_release(start_button);
    safe_release(taskbar_frame);
    safe_release(root);
    return layout;
}

void TaskbarLocator::shutdown() {
    delete impl_;
    impl_ = nullptr;
}

}  // namespace tasklyric::native
