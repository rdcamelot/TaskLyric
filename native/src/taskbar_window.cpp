#include "tasklyric/taskbar_window.hpp"

#include "tasklyric/taskbar_dcomp_renderer.hpp"

#include <windows.h>
#include <windowsx.h>

#include <algorithm>
#include <cmath>
#include <array>
#include <filesystem>
#include <fstream>
#include <objbase.h>
#include <sstream>
#include <string_view>

namespace tasklyric::native {
namespace {

constexpr wchar_t kWindowClassName[] = L"TaskLyric.TaskbarWindow";
constexpr UINT kRefreshMessage = WM_APP + 1;
constexpr UINT_PTR kLayoutTimerId = 1;
constexpr UINT kLayoutTimerIntervalMs = 33;
constexpr double kLayoutAnimationTimeConstantMs = 110.0;
constexpr int kRectAnimationSnapPx = 1;
constexpr int kPreferredWidth = 560;
constexpr int kMinimumWidth = 220;
constexpr int kFallbackHeight = 48;
constexpr int kPaddingX = 12;
constexpr int kPaddingY = 6;
constexpr int kAnchorGap = 6;
constexpr int kControlButtonSize = 24;
constexpr int kControlButtonGap = 5;
constexpr int kControlCompactButtonSize = 21;
constexpr int kControlCompactButtonGap = 3;
constexpr int kControlHitPadding = 5;
constexpr int kControlRightInset = 16;
constexpr int kControlCompactRightInset = 12;
constexpr int kControlMinWidth = 360;
constexpr int kControlCompactMinWidth = 290;
constexpr int kControlTextGap = 12;
constexpr int kControlCompactTextGap = 8;
constexpr int kControlCompactMinTextWidth = 92;

void append_debug_line(const wchar_t* line) {
    const std::filesystem::path path = std::filesystem::current_path() / "logs" / "tasklyric-window.log";
    std::error_code ec;
    std::filesystem::create_directories(path.parent_path(), ec);
    std::ofstream stream(path, std::ios::app | std::ios::binary);
    if (!stream) {
        return;
    }
    std::wstring_view view = line ? std::wstring_view(line) : std::wstring_view();
    std::string utf8;
    if (!view.empty()) {
        const int size = WideCharToMultiByte(CP_UTF8, 0, view.data(), static_cast<int>(view.size()), nullptr, 0, nullptr, nullptr);
        if (size > 0) {
            utf8.resize(size);
            WideCharToMultiByte(CP_UTF8, 0, view.data(), static_cast<int>(view.size()), utf8.data(), size, nullptr, nullptr);
        }
    }
    utf8 += "\n";
    stream.write(utf8.data(), static_cast<std::streamsize>(utf8.size()));
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

HINSTANCE current_module_handle() {
    HMODULE module = nullptr;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&current_module_handle),
        &module
    );
    return module;
}

int dpi_scaled_font_height(int point_size) {
    HDC screen = GetDC(nullptr);
    const int dpi = screen ? GetDeviceCaps(screen, LOGPIXELSY) : 96;
    if (screen) {
        ReleaseDC(nullptr, screen);
    }
    return -MulDiv(point_size, dpi, 72);
}

UINT draw_text_flags(std::wstring_view align) {
    UINT flags = DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX;
    if (align == L"left") {
        return flags | DT_LEFT;
    }
    if (align == L"right") {
        return flags | DT_RIGHT;
    }
    return flags | DT_CENTER;
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

RECT offset_rect(const RECT& rect, int dx, int dy) {
    if (!is_valid_rect(rect)) {
        return empty_rect();
    }

    RECT shifted = rect;
    OffsetRect(&shifted, dx, dy);
    return shifted;
}

RECT child_screen_rect(HWND parent, const wchar_t* class_name) {
    HWND child = FindWindowExW(parent, nullptr, class_name, nullptr);
    if (!child) {
        return empty_rect();
    }

    RECT rect{};
    if (!GetWindowRect(child, &rect)) {
        return empty_rect();
    }
    return rect;
}

bool rects_intersect(const RECT& left, const RECT& right) {
    if (!is_valid_rect(left) || !is_valid_rect(right)) {
        return false;
    }

    RECT intersection{};
    return IntersectRect(&intersection, &left, &right) == TRUE;
}

int rect_width(const RECT& rect) {
    return std::max(0, static_cast<int>(rect.right - rect.left));
}

int rect_height(const RECT& rect) {
    return std::max(0, static_cast<int>(rect.bottom - rect.top));
}

bool same_rect(const RECT& left, const RECT& right) {
    return left.left == right.left && left.top == right.top && left.right == right.right && left.bottom == right.bottom;
}

bool rect_is_close(const RECT& left, const RECT& right, int tolerance = kRectAnimationSnapPx) {
    return std::abs(left.left - right.left) <= tolerance
        && std::abs(left.top - right.top) <= tolerance
        && std::abs(left.right - right.right) <= tolerance
        && std::abs(left.bottom - right.bottom) <= tolerance;
}

LONG animate_coordinate(LONG current, LONG target, double alpha) {
    const double blended = static_cast<double>(current) + (static_cast<double>(target) - static_cast<double>(current)) * alpha;
    return static_cast<LONG>(std::lround(blended));
}

RECT animate_rect_towards(const RECT& current, const RECT& target, double alpha) {
    RECT animated{};
    animated.left = animate_coordinate(current.left, target.left, alpha);
    animated.top = animate_coordinate(current.top, target.top, alpha);
    animated.right = animate_coordinate(current.right, target.right, alpha);
    animated.bottom = animate_coordinate(current.bottom, target.bottom, alpha);
    return animated;
}

bool child_rect_in_parent(HWND parent, const wchar_t* class_name, RECT* rect) {
    HWND child = FindWindowExW(parent, nullptr, class_name, nullptr);
    if (!child) {
        return false;
    }

    RECT screen_rect{};
    if (!GetWindowRect(child, &screen_rect)) {
        return false;
    }

    POINT points[2] = {
        { screen_rect.left, screen_rect.top },
        { screen_rect.right, screen_rect.bottom },
    };
    MapWindowPoints(HWND_DESKTOP, parent, points, 2);

    rect->left = points[0].x;
    rect->top = points[0].y;
    rect->right = points[1].x;
    rect->bottom = points[1].y;
    return true;
}

std::wstring rect_json(const RECT& rect) {
    std::wostringstream stream;
    stream << L"[" << rect.left << L"," << rect.top << L"," << rect.right << L"," << rect.bottom << L"]";
    return stream.str();
}

}  // namespace

TaskbarControlLayout compute_taskbar_control_layout(UINT width, UINT height, UINT task_list_right) {
    TaskbarControlLayout layout{};
    layout.text_rect = {0, 0, static_cast<LONG>(width), static_cast<LONG>(height)};

    const int width_i = static_cast<int>(width);
    const int height_i = static_cast<int>(height);
    if (height_i < 34 || width_i < kControlCompactMinWidth) {
        return layout;
    }

    const bool compact = width_i < kControlMinWidth;
    const int button_size = compact ? kControlCompactButtonSize : kControlButtonSize;
    const int button_gap = compact ? kControlCompactButtonGap : kControlButtonGap;
    const int right_inset = compact ? kControlCompactRightInset : kControlRightInset;
    const int text_gap = compact ? kControlCompactTextGap : kControlTextGap;
    const int min_text_width = compact ? kControlCompactMinTextWidth : static_cast<int>(task_list_right);
    const int total_width = (button_size * 3) + (button_gap * 2);
    const int group_right = width_i - right_inset;
    const int group_left = group_right - total_width;
    if (group_left <= min_text_width) {
        return layout;
    }

    const int top = std::max(compact ? 5 : 6, (height_i - button_size) / 2);
    layout.visible = true;
    layout.previous_rect = {group_left, top, group_left + button_size, top + button_size};
    layout.toggle_rect = {layout.previous_rect.right + button_gap, top, layout.previous_rect.right + button_gap + button_size, top + button_size};
    layout.next_rect = {layout.toggle_rect.right + button_gap, top, layout.toggle_rect.right + button_gap + button_size, top + button_size};
    layout.text_rect = RECT{0, 0, static_cast<LONG>(std::max(0L, layout.previous_rect.left - static_cast<LONG>(text_gap))), static_cast<LONG>(height_i)};
    return layout;
}

std::wstring_view taskbar_control_action_name(TaskbarControlAction action) {
    switch (action) {
    case TaskbarControlAction::previous:
        return L"previous";
    case TaskbarControlAction::toggle_playback:
        return L"toggle-play-pause";
    case TaskbarControlAction::next_track:
        return L"next";
    default:
        return L"";
    }
}

TaskbarWindow::~TaskbarWindow() = default;

TaskbarWindow& TaskbarWindow::instance() {
    static TaskbarWindow window;
    return window;
}

bool TaskbarWindow::start() {
    HANDLE ready_event = nullptr;
    {
        std::scoped_lock lock(mutex_);
        if (running_) {
            return true;
        }
        ready_event_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!ready_event_) {
            return false;
        }
        ready_event = ready_event_;
        running_ = true;
        thread_ = std::thread(&TaskbarWindow::thread_main, this);
    }

    const DWORD wait_result = WaitForSingleObject(ready_event, 5000);
    if (wait_result != WAIT_OBJECT_0) {
        append_debug_line(L"start: ready event timeout");
        return false;
    }

    std::scoped_lock lock(mutex_);
    return hwnd_ != nullptr;
}

void TaskbarWindow::stop() {
    std::thread thread;
    HANDLE ready_event = nullptr;
    DWORD thread_id = 0;
    HWND hwnd = nullptr;
    {
        std::scoped_lock lock(mutex_);
        if (!running_ && !thread_.joinable()) {
            if (ready_event_) {
                CloseHandle(ready_event_);
                ready_event_ = nullptr;
            }
            return;
        }
        hwnd = hwnd_;
        thread_id = thread_id_;
        ready_event = ready_event_;
        thread = std::move(thread_);
    }

    if (hwnd) {
        PostMessageW(hwnd, WM_CLOSE, 0, 0);
    } else if (thread_id != 0) {
        PostThreadMessageW(thread_id, WM_QUIT, 0, 0);
    }

    if (thread.joinable()) {
        thread.join();
    }

    if (ready_event) {
        CloseHandle(ready_event);
    }

    std::scoped_lock lock(mutex_);
    ready_event_ = nullptr;
    thread_id_ = 0;
}

void TaskbarWindow::update_config(const TaskbarConfig& config) {
    std::scoped_lock lock(mutex_);
    config_ = config;
    destroy_fonts_locked();
    ensure_fonts_locked();
    if (hwnd_) {
        PostMessageW(hwnd_, kRefreshMessage, 0, 0);
    }
}

void TaskbarWindow::update_lyric(const TaskbarLyricState& state) {
    std::scoped_lock lock(mutex_);
    lyric_state_ = state;
    if (hwnd_) {
        PostMessageW(hwnd_, kRefreshMessage, 0, 0);
    }
}

std::wstring TaskbarWindow::snapshot_json() const {
    std::scoped_lock lock(mutex_);
    return snapshot_json_locked();
}

std::wstring TaskbarWindow::take_pending_command_json() {
    std::scoped_lock lock(mutex_);
    std::wstring value = pending_command_json_;
    pending_command_json_.clear();
    return value;
}

LRESULT CALLBACK TaskbarWindow::window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    TaskbarWindow* self = reinterpret_cast<TaskbarWindow*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));

    if (message == WM_NCCREATE) {
        auto* create = reinterpret_cast<CREATESTRUCTW*>(lparam);
        self = reinterpret_cast<TaskbarWindow*>(create->lpCreateParams);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        return TRUE;
    }

    if (!self) {
        return DefWindowProcW(hwnd, message, wparam, lparam);
    }

    switch (message) {
    case WM_NCHITTEST: {
        POINT point = { GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam) };
        ScreenToClient(hwnd, &point);
        std::scoped_lock lock(self->mutex_);
        return self->hit_test_control_locked(point) == TaskbarControlAction::none ? HTTRANSPARENT : HTCLIENT;
    }
    case WM_SETCURSOR: {
        if (LOWORD(lparam) != HTCLIENT) {
            return DefWindowProcW(hwnd, message, wparam, lparam);
        }
        POINT point{};
        GetCursorPos(&point);
        ScreenToClient(hwnd, &point);
        std::scoped_lock lock(self->mutex_);
        const auto action = self->hit_test_control_locked(point);
        SetCursor(LoadCursorW(nullptr, action == TaskbarControlAction::none ? IDC_ARROW : IDC_HAND));
        return TRUE;
    }
    case WM_MOUSEACTIVATE:
        return MA_NOACTIVATE;
    case WM_ERASEBKGND:
        return 1;
    case WM_MOUSEMOVE: {
        POINT point = { GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam) };
        std::scoped_lock lock(self->mutex_);
        self->set_hot_action_locked(self->hit_test_control_locked(point));
        self->track_mouse_leave();
        return 0;
    }
    case WM_MOUSELEAVE: {
        std::scoped_lock lock(self->mutex_);
        self->tracking_mouse_leave_ = false;
        self->set_hot_action_locked(TaskbarControlAction::none);
        return 0;
    }
    case WM_LBUTTONDOWN: {
        POINT point = { GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam) };
        TaskbarControlAction action = TaskbarControlAction::none;
        {
            std::scoped_lock lock(self->mutex_);
            action = self->hit_test_control_locked(point);
            self->set_pressed_action_locked(action);
        }
        if (action != TaskbarControlAction::none) {
            SetCapture(hwnd);
            return 0;
        }
        break;
    }
    case WM_LBUTTONUP: {
        POINT point = { GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam) };
        TaskbarControlAction action = TaskbarControlAction::none;
        bool should_queue = false;
        {
            std::scoped_lock lock(self->mutex_);
            action = self->hit_test_control_locked(point);
            const auto pressed = self->ui_state_.pressed_action;
            self->set_pressed_action_locked(TaskbarControlAction::none);
            self->set_hot_action_locked(action);
            should_queue = pressed != TaskbarControlAction::none && pressed == action;
        }
        if (GetCapture() == hwnd) {
            ReleaseCapture();
        }
        if (should_queue) {
            std::scoped_lock lock(self->mutex_);
            self->queue_control_locked(action);
            return 0;
        }
        break;
    }
    case WM_CAPTURECHANGED: {
        std::scoped_lock lock(self->mutex_);
        self->set_pressed_action_locked(TaskbarControlAction::none);
        return 0;
    }
    case WM_SIZE: {
        std::scoped_lock lock(self->mutex_);
        self->window_width_ = static_cast<UINT>(LOWORD(lparam));
        self->window_height_ = static_cast<UINT>(HIWORD(lparam));
        if (self->renderer_ && self->composition_ready_ && self->window_width_ > 0 && self->window_height_ > 0) {
            self->renderer_->resize(self->window_width_, self->window_height_);
        }
        return 0;
    }
    case WM_TIMER:
        self->refresh_window();
        return 0;
    case kRefreshMessage:
        self->refresh_window();
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT paint{};
        HDC hdc = BeginPaint(hwnd, &paint);
        {
            std::scoped_lock lock(self->mutex_);
            if (!self->render_with_composition_locked()) {
                self->paint_locked(hdc);
            }
        }
        EndPaint(hwnd, &paint);
        return 0;
    }
    case WM_DESTROY:
        KillTimer(hwnd, kLayoutTimerId);
        PostQuitMessage(0);
        return 0;
    default:
        return DefWindowProcW(hwnd, message, wparam, lparam);
    }

    return DefWindowProcW(hwnd, message, wparam, lparam);
}

void TaskbarWindow::thread_main() {
    const HRESULT co_result = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
    const bool should_uninitialize = SUCCEEDED(co_result);

    HINSTANCE module = current_module_handle();

    WNDCLASSW window_class{};
    window_class.lpfnWndProc = &TaskbarWindow::window_proc;
    window_class.hInstance = module;
    window_class.lpszClassName = kWindowClassName;
    window_class.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    RegisterClassW(&window_class);

    HWND parent = FindWindowW(L"Shell_TrayWnd", nullptr);
    const DWORD style = parent ? (WS_CHILD | WS_VISIBLE) : (WS_POPUP | WS_VISIBLE | WS_DISABLED);
    const DWORD ex_style = parent
        ? (WS_EX_NOPARENTNOTIFY | WS_EX_NOACTIVATE | WS_EX_NOREDIRECTIONBITMAP)
        : (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE);

    HWND hwnd = CreateWindowExW(
        ex_style,
        kWindowClassName,
        L"TaskLyric",
        style,
        0,
        0,
        kPreferredWidth,
        kFallbackHeight,
        parent,
        nullptr,
        module,
        this
    );

    {
        std::scoped_lock lock(mutex_);
        hwnd_ = hwnd;
        parent_hwnd_ = parent;
        thread_id_ = GetCurrentThreadId();
        attached_ = parent != nullptr;
        ensure_fonts_locked();
        renderer_ = std::make_unique<TaskbarDCompRenderer>();
        composition_ready_ = false;
        composition_attempted_ = false;
        window_width_ = kPreferredWidth;
        window_height_ = kFallbackHeight;
        ui_state_ = {};
        pending_command_json_.clear();
        tracking_mouse_leave_ = false;
        last_layout_ = {};
        target_screen_rect_ = {};
        animated_screen_rect_ = {};
        layout_transition_active_ = false;
        last_animation_tick_ = 0;
        if (attached_) {
            locator_.initialize(parent_hwnd_);
        }
    }

    if (ready_event_) {
        SetEvent(ready_event_);
    }

    if (!hwnd) {
        std::scoped_lock lock(mutex_);
        running_ = false;
        if (should_uninitialize) {
            CoUninitialize();
        }
        return;
    }

    ShowWindow(hwnd, SW_SHOWNOACTIVATE);
    SetTimer(hwnd, kLayoutTimerId, kLayoutTimerIntervalMs, nullptr);
    refresh_window();

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }

    {
        std::scoped_lock lock(mutex_);
        locator_.shutdown();
        if (renderer_) {
            renderer_->shutdown();
        }
        composition_ready_ = false;
        composition_attempted_ = false;
        destroy_fonts_locked();
        hwnd_ = nullptr;
        parent_hwnd_ = nullptr;
        attached_ = false;
        running_ = false;
        window_width_ = 0;
        window_height_ = 0;
        ui_state_ = {};
        pending_command_json_.clear();
        tracking_mouse_leave_ = false;
        last_layout_ = {};
        target_screen_rect_ = {};
        animated_screen_rect_ = {};
        layout_transition_active_ = false;
        last_animation_tick_ = 0;
    }

    UnregisterClassW(kWindowClassName, module);
    if (should_uninitialize) {
        CoUninitialize();
    }
}

void TaskbarWindow::ensure_fonts_locked() {
    if (main_font_ && sub_font_) {
        return;
    }

    main_font_ = CreateFontW(
        dpi_scaled_font_height(config_.font_size),
        0,
        0,
        0,
        FW_MEDIUM,
        FALSE,
        FALSE,
        FALSE,
        DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS,
        CLEARTYPE_QUALITY,
        DEFAULT_PITCH | FF_DONTCARE,
        config_.font_family.c_str()
    );

    const int sub_size = std::max(11, config_.font_size - 3);
    sub_font_ = CreateFontW(
        dpi_scaled_font_height(sub_size),
        0,
        0,
        0,
        FW_NORMAL,
        FALSE,
        FALSE,
        FALSE,
        DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS,
        CLEARTYPE_QUALITY,
        DEFAULT_PITCH | FF_DONTCARE,
        config_.font_family.c_str()
    );
}

void TaskbarWindow::destroy_fonts_locked() {
    if (main_font_) {
        DeleteObject(main_font_);
        main_font_ = nullptr;
    }
    if (sub_font_) {
        DeleteObject(sub_font_);
        sub_font_ = nullptr;
    }
}

void TaskbarWindow::reset_renderer_locked(const wchar_t* reason) {
    if (!renderer_ || !composition_ready_) {
        return;
    }
    if (reason && *reason) {
        append_debug_line((std::wstring(L"renderer reset: ") + reason).c_str());
    }
    renderer_->shutdown();
    renderer_ = std::make_unique<TaskbarDCompRenderer>();
    composition_ready_ = false;
    composition_attempted_ = false;
}

bool TaskbarWindow::compute_target_rect_locked(RECT* screen_rect) {
    if (!screen_rect) {
        return false;
    }

    *screen_rect = empty_rect();

    HWND parent_hwnd = nullptr;
    bool attached = false;
    {
        std::scoped_lock lock(mutex_);
        parent_hwnd = parent_hwnd_;
        attached = attached_;
    }

    auto commit_layout = [this](const TaskbarLayout& layout) {
        std::scoped_lock lock(mutex_);
        last_layout_ = layout;
    };

    auto compute_live_taskbar_layout = [&](TaskbarLayout* layout, RECT* resolved_rect) -> bool {
        if (!layout || !resolved_rect || !attached || !parent_hwnd || !IsWindow(parent_hwnd)) {
            return false;
        }

        RECT parent_rect{};
        RECT client{};
        if (!GetWindowRect(parent_hwnd, &parent_rect) || !GetClientRect(parent_hwnd, &client)) {
            return false;
        }

        const int width = client.right - client.left;
        const int height = client.bottom - client.top;
        if (width <= 0 || height <= 0) {
            return false;
        }

        const int window_height = std::clamp(height - 2, 32, 60);
        const int y = std::max(0, (height - window_height) / 2);

        RECT start_rect{};
        RECT task_switcher_rect{};
        RECT rebar_rect{};
        RECT tray_rect{};
        child_rect_in_parent(parent_hwnd, L"Start", &start_rect);
        child_rect_in_parent(parent_hwnd, L"MSTaskSwWClass", &task_switcher_rect);
        child_rect_in_parent(parent_hwnd, L"ReBarWindow32", &rebar_rect);
        child_rect_in_parent(parent_hwnd, L"TrayNotifyWnd", &tray_rect);

        RECT anchor_rect = union_rect(start_rect, task_switcher_rect);
        anchor_rect = union_rect(anchor_rect, rebar_rect);

        int x = kPaddingX;
        int window_width = std::clamp(kPreferredWidth, kMinimumWidth, std::max(kMinimumWidth, width - (kPaddingX * 2)));
        std::wstring source = L"window-live-center";

        if (is_valid_rect(anchor_rect)) {
            const int left_available = anchor_rect.left - kAnchorGap - (kPaddingX * 2);
            if (left_available >= kMinimumWidth) {
                window_width = std::min(kPreferredWidth, left_available);
                x = std::max(kPaddingX, static_cast<int>(anchor_rect.left) - kAnchorGap - window_width);
                source = L"window-live-left-of-start";
            } else if (is_valid_rect(tray_rect)) {
                const int between = tray_rect.left - anchor_rect.right - (kPaddingX * 2);
                if (between >= kMinimumWidth) {
                    window_width = std::min(kPreferredWidth, between);
                    x = anchor_rect.right + std::max(kPaddingX, (between - window_width) / 2);
                    source = L"window-live-between-tasklist-tray";
                }
            }
        }

        resolved_rect->left = parent_rect.left + x;
        resolved_rect->top = parent_rect.top + y;
        resolved_rect->right = resolved_rect->left + window_width;
        resolved_rect->bottom = resolved_rect->top + window_height;

        layout->valid = true;
        layout->centered = false;
        layout->widgets_enabled = false;
        layout->source = source;
        layout->taskbar_frame = parent_rect;
        layout->task_list = offset_rect(anchor_rect, parent_rect.left, parent_rect.top);
        layout->tray_frame = offset_rect(tray_rect, parent_rect.left, parent_rect.top);
        layout->widgets_button = {};
        layout->lyric_rect = *resolved_rect;
        return true;
    };

    if (attached && parent_hwnd && IsWindow(parent_hwnd)) {
        TaskbarLayout layout{};
        if (compute_live_taskbar_layout(&layout, screen_rect)) {
            commit_layout(layout);
            return true;
        }

        layout = locator_.query();
        const RECT start_screen = child_screen_rect(parent_hwnd, L"Start");
        const RECT task_switcher_screen = child_screen_rect(parent_hwnd, L"MSTaskSwWClass");
        const RECT tray_screen = child_screen_rect(parent_hwnd, L"TrayNotifyWnd");
        const bool overlaps_shell = rects_intersect(layout.lyric_rect, start_screen)
            || rects_intersect(layout.lyric_rect, task_switcher_screen)
            || rects_intersect(layout.lyric_rect, tray_screen);
        if (layout.valid && is_valid_rect(layout.lyric_rect) && !overlaps_shell) {
            commit_layout(layout);
            *screen_rect = layout.lyric_rect;
            return true;
        }
    }

    RECT work{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    screen_rect->left = work.left + ((work.right - work.left) - kPreferredWidth) / 2;
    screen_rect->top = work.bottom - kFallbackHeight - 8;
    screen_rect->right = screen_rect->left + kPreferredWidth;
    screen_rect->bottom = screen_rect->top + kFallbackHeight;

    TaskbarLayout layout{};
    layout.valid = true;
    layout.centered = false;
    layout.widgets_enabled = false;
    layout.source = L"work-area-fallback";
    layout.taskbar_frame = work;
    layout.task_list = {};
    layout.tray_frame = {};
    layout.widgets_button = {};
    layout.lyric_rect = *screen_rect;
    commit_layout(layout);
    return true;
}

void TaskbarWindow::apply_window_rect(const RECT& screen_rect) {
    if (!hwnd_ || !is_valid_rect(screen_rect)) {
        return;
    }

    HWND parent_hwnd = nullptr;
    bool attached = false;
    {
        std::scoped_lock lock(mutex_);
        parent_hwnd = parent_hwnd_;
        attached = attached_;
    }

    RECT reference_rect{};
    if (attached && parent_hwnd && IsWindow(parent_hwnd)) {
        GetWindowRect(parent_hwnd, &reference_rect);
    }

    const int x = screen_rect.left - reference_rect.left;
    const int y = screen_rect.top - reference_rect.top;
    const int width = std::max(0, static_cast<int>(screen_rect.right - screen_rect.left));
    const int height = std::max(0, static_cast<int>(screen_rect.bottom - screen_rect.top));
    if (width <= 0 || height <= 0) {
        return;
    }

    RECT current{};
    GetWindowRect(hwnd_, &current);
    const bool changed = current.left != screen_rect.left || current.top != screen_rect.top || current.right != screen_rect.right || current.bottom != screen_rect.bottom;

    if (changed) {
        MoveWindow(hwnd_, x, y, width, height, FALSE);
    }
    BringWindowToTop(hwnd_);
    ShowWindow(hwnd_, SW_SHOWNOACTIVATE);

    {
        std::scoped_lock lock(mutex_);
        const UINT next_width = static_cast<UINT>(width);
        const UINT next_height = static_cast<UINT>(height);
        const bool geometry_changed = changed || next_width != window_width_ || next_height != window_height_;
        window_width_ = next_width;
        window_height_ = next_height;
        if (geometry_changed && renderer_ && composition_ready_) {
            reset_renderer_locked(L"snap-layout-change");
        } else if (renderer_ && composition_ready_) {
            renderer_->resize(window_width_, window_height_);
        }
    }

    if (changed) {
        RedrawWindow(hwnd_, nullptr, nullptr, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN);
    }
}

void TaskbarWindow::refresh_window() {
    RECT screen_rect{};
    compute_target_rect_locked(&screen_rect);

    {
        std::scoped_lock lock(mutex_);
        target_screen_rect_ = screen_rect;
        animated_screen_rect_ = screen_rect;
        layout_transition_active_ = false;
        last_animation_tick_ = GetTickCount64();
    }

    if (is_valid_rect(screen_rect)) {
        apply_window_rect(screen_rect);
    }

    bool rendered = false;
    {
        std::scoped_lock lock(mutex_);
        rendered = render_with_composition_locked();
    }

    if (!rendered && hwnd_) {
        InvalidateRect(hwnd_, nullptr, TRUE);
    }
}

bool TaskbarWindow::render_with_composition_locked() {
    if (!renderer_ || !hwnd_ || window_width_ == 0 || window_height_ == 0) {
        return false;
    }

    if (!composition_ready_ && !composition_attempted_) {
        composition_attempted_ = true;
        composition_ready_ = renderer_->initialize(hwnd_);
        if (composition_ready_) {
            renderer_->resize(window_width_, window_height_);
        }
    }

    if (!composition_ready_) {
        return false;
    }

    return renderer_->render(config_, lyric_state_, ui_state_, window_width_, window_height_);
}

void TaskbarWindow::paint_locked(HDC hdc) {
    RECT client{};
    GetClientRect(hwnd_, &client);

    if (config_.debug_fill) {
        HBRUSH debug_background = CreateSolidBrush(config_.debug_fill_color);
        FillRect(hdc, &client, debug_background);
        DeleteObject(debug_background);
    } else if (attached_ && parent_hwnd_ && IsWindow(parent_hwnd_)) {
        SendMessageW(parent_hwnd_, WM_PRINTCLIENT, reinterpret_cast<WPARAM>(hdc), PRF_CLIENT | PRF_ERASEBKGND);
    } else {
        HBRUSH background = CreateSolidBrush(RGB(24, 26, 30));
        FillRect(hdc, &client, background);
        DeleteObject(background);
    }

    SetBkMode(hdc, TRANSPARENT);

    RECT main_rect = client;
    RECT sub_rect = client;
    main_rect.left += kPaddingX;
    main_rect.right -= kPaddingX;
    main_rect.top += kPaddingY - 1;
    main_rect.bottom = main_rect.top + std::max(16, config_.font_size + 6);

    sub_rect.left += kPaddingX;
    sub_rect.right -= kPaddingX;
    sub_rect.top = main_rect.bottom - 1;
    sub_rect.bottom -= kPaddingY;

    const UINT flags = draw_text_flags(config_.align);
    std::array<RECT, 2> shadow_rects = { main_rect, sub_rect };
    OffsetRect(&shadow_rects[0], 1, 1);
    OffsetRect(&shadow_rects[1], 1, 1);

    ensure_fonts_locked();

    SelectObject(hdc, main_font_);
    SetTextColor(hdc, config_.shadow_color);
    DrawTextW(hdc, lyric_state_.main_text.c_str(), -1, &shadow_rects[0], flags | DT_VCENTER);
    SetTextColor(hdc, config_.text_color);
    DrawTextW(hdc, lyric_state_.main_text.c_str(), -1, &main_rect, flags | DT_VCENTER);

    const std::wstring sub_text = lyric_state_.sub_text.empty() ? lyric_state_.artist : lyric_state_.sub_text;
    if (!sub_text.empty()) {
        SelectObject(hdc, sub_font_);
        SetTextColor(hdc, config_.shadow_color);
        DrawTextW(hdc, sub_text.c_str(), -1, &shadow_rects[1], flags | DT_VCENTER);
        SetTextColor(hdc, config_.sub_text_color);
        DrawTextW(hdc, sub_text.c_str(), -1, &sub_rect, flags | DT_VCENTER);
    }

    if (config_.debug_border_thickness > 0) {
        HPEN pen = CreatePen(PS_SOLID, config_.debug_border_thickness, config_.debug_border_color);
        HGDIOBJ old_pen = SelectObject(hdc, pen);
        HGDIOBJ old_brush = SelectObject(hdc, GetStockObject(HOLLOW_BRUSH));
        Rectangle(hdc, client.left, client.top, client.right, client.bottom);
        SelectObject(hdc, old_brush);
        SelectObject(hdc, old_pen);
        DeleteObject(pen);
    }
}

TaskbarControlAction TaskbarWindow::hit_test_control_locked(POINT point) const {
    const TaskbarControlLayout layout = compute_taskbar_control_layout(window_width_, window_height_);
    if (!layout.visible) {
        return TaskbarControlAction::none;
    }

    auto contains = [&](RECT rect) {
        InflateRect(&rect, kControlHitPadding, kControlHitPadding);
        return PtInRect(&rect, point) != 0;
    };

    if (contains(layout.previous_rect)) {
        return TaskbarControlAction::previous;
    }
    if (contains(layout.toggle_rect)) {
        return TaskbarControlAction::toggle_playback;
    }
    if (contains(layout.next_rect)) {
        return TaskbarControlAction::next_track;
    }
    return TaskbarControlAction::none;
}

void TaskbarWindow::set_hot_action_locked(TaskbarControlAction action) {
    if (ui_state_.hot_action == action) {
        return;
    }
    ui_state_.hot_action = action;
    if (hwnd_) {
        InvalidateRect(hwnd_, nullptr, FALSE);
        PostMessageW(hwnd_, kRefreshMessage, 0, 0);
    }
}

void TaskbarWindow::set_pressed_action_locked(TaskbarControlAction action) {
    if (ui_state_.pressed_action == action) {
        return;
    }
    ui_state_.pressed_action = action;
    if (hwnd_) {
        InvalidateRect(hwnd_, nullptr, FALSE);
        PostMessageW(hwnd_, kRefreshMessage, 0, 0);
    }
}

void TaskbarWindow::queue_control_locked(TaskbarControlAction action) {
    std::wstring_view command = taskbar_control_action_name(action);
    if (command.empty()) {
        return;
    }

    if (action == TaskbarControlAction::toggle_playback) {
        if (_wcsicmp(lyric_state_.playback_state.c_str(), L"playing") == 0) {
            command = L"pause";
        } else if (_wcsicmp(lyric_state_.playback_state.c_str(), L"paused") == 0) {
            command = L"play";
        }
    }

    pending_command_json_ = std::wstring(L"{\"action\":\"") + std::wstring(command) + L"\",\"source\":\"taskbar-control\"}";
    append_debug_line((std::wstring(L"control queued: ") + std::wstring(command)).c_str());
    if (hwnd_) {
        PostMessageW(hwnd_, kRefreshMessage, 0, 0);
    }
}

void TaskbarWindow::track_mouse_leave() {
    if (!hwnd_ || tracking_mouse_leave_) {
        return;
    }
    TRACKMOUSEEVENT event{};
    event.cbSize = sizeof(event);
    event.dwFlags = TME_LEAVE;
    event.hwndTrack = hwnd_;
    if (TrackMouseEvent(&event)) {
        tracking_mouse_leave_ = true;
    }
}

std::wstring TaskbarWindow::snapshot_json_locked() const {
    RECT rect{};
    if (hwnd_) {
        GetWindowRect(hwnd_, &rect);
    }

    std::wostringstream stream;
    stream << L"{"
           << L"\"running\":" << (running_ ? L"true" : L"false")
           << L",\"attached\":" << (attached_ ? L"true" : L"false")
           << L",\"hasHwnd\":" << (hwnd_ ? L"true" : L"false")
           << L",\"compositionReady\":" << (composition_ready_ ? L"true" : L"false")
           << L",\"mainText\":\"" << escape_json(lyric_state_.main_text) << L"\""
           << L",\"subText\":\"" << escape_json(lyric_state_.sub_text) << L"\""
           << L",\"playbackState\":\"" << escape_json(lyric_state_.playback_state) << L"\""
           << L",\"fontFamily\":\"" << escape_json(config_.font_family) << L"\""
           << L",\"fontSize\":" << config_.font_size
           << L",\"debugFill\":" << (config_.debug_fill ? L"true" : L"false")
           << L",\"debugBorderThickness\":" << config_.debug_border_thickness
           << L",\"rect\":" << rect_json(rect)
           << L",\"layout\":{"
           << L"\"valid\":" << (last_layout_.valid ? L"true" : L"false")
           << L",\"source\":\"" << escape_json(last_layout_.source) << L"\""
           << L",\"centered\":" << (last_layout_.centered ? L"true" : L"false")
           << L",\"widgetsEnabled\":" << (last_layout_.widgets_enabled ? L"true" : L"false")
           << L",\"taskbarFrame\":" << rect_json(last_layout_.taskbar_frame)
           << L",\"taskList\":" << rect_json(last_layout_.task_list)
           << L",\"trayFrame\":" << rect_json(last_layout_.tray_frame)
           << L",\"widgetsButton\":" << rect_json(last_layout_.widgets_button)
           << L",\"lyricRect\":" << rect_json(last_layout_.lyric_rect)
           << L"}"
           << L",\"renderer\":" << (renderer_ ? renderer_->snapshot_json() : L"null")
           << L"}";
    return stream.str();
}

}  // namespace tasklyric::native


