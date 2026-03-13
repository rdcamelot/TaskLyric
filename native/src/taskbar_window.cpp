#include "tasklyric/taskbar_window.hpp"

#include "tasklyric/taskbar_dcomp_renderer.hpp"

#include <windows.h>

#include <algorithm>
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
constexpr int kPreferredWidth = 560;
constexpr int kMinimumWidth = 220;
constexpr int kFallbackHeight = 48;
constexpr int kPaddingX = 12;
constexpr int kPaddingY = 6;
constexpr int kAnchorGap = 6;

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
    case WM_NCHITTEST:
        return HTTRANSPARENT;
    case WM_MOUSEACTIVATE:
        return MA_NOACTIVATE;
    case WM_ERASEBKGND:
        return 1;
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
        ? (WS_EX_NOPARENTNOTIFY | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_NOREDIRECTIONBITMAP)
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
        last_layout_ = {};
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
    SetTimer(hwnd, kLayoutTimerId, 800, nullptr);
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
        last_layout_ = {};
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

bool TaskbarWindow::compute_target_rect_locked(RECT* screen_rect) {
    if (!screen_rect) {
        return false;
    }

    *screen_rect = empty_rect();

    if (attached_ && parent_hwnd_ && IsWindow(parent_hwnd_)) {
        TaskbarLayout layout = locator_.query();
        if (layout.valid && is_valid_rect(layout.lyric_rect)) {
            last_layout_ = layout;
            *screen_rect = layout.lyric_rect;
            return true;
        }

        RECT parent_rect{};
        RECT client{};
        if (GetWindowRect(parent_hwnd_, &parent_rect) && GetClientRect(parent_hwnd_, &client)) {
            const int width = client.right - client.left;
            const int height = client.bottom - client.top;
            const int window_height = std::clamp(height - 2, 32, 60);
            const int y = std::max(0, (height - window_height) / 2);

            RECT anchor_rect{};
            bool has_anchor = child_rect_in_parent(parent_hwnd_, L"Start", &anchor_rect);
            if (!has_anchor) {
                has_anchor = child_rect_in_parent(parent_hwnd_, L"MSTaskSwWClass", &anchor_rect);
            }
            if (!has_anchor) {
                has_anchor = child_rect_in_parent(parent_hwnd_, L"ReBarWindow32", &anchor_rect);
            }

            RECT tray_rect{};
            const bool has_tray = child_rect_in_parent(parent_hwnd_, L"TrayNotifyWnd", &tray_rect);

            int x = kPaddingX;
            int window_width = std::clamp(kPreferredWidth, kMinimumWidth, std::max(kMinimumWidth, width - (kPaddingX * 2)));
            std::wstring source = L"window-fallback-center";

            if (has_anchor) {
                const int left_available = anchor_rect.left - kAnchorGap - (kPaddingX * 2);
                if (left_available >= kMinimumWidth) {
                    window_width = std::min(kPreferredWidth, left_available);
                    x = std::max(kPaddingX, static_cast<int>(anchor_rect.left) - kAnchorGap - window_width);
                    source = L"window-fallback-left-of-start";
                } else if (has_tray) {
                    const int between = tray_rect.left - anchor_rect.right - (kPaddingX * 2);
                    if (between >= kMinimumWidth) {
                        window_width = std::min(kPreferredWidth, between);
                        x = anchor_rect.right + std::max(kPaddingX, (between - window_width) / 2);
                        source = L"window-fallback-between-tasklist-tray";
                    }
                }
            }

            screen_rect->left = parent_rect.left + x;
            screen_rect->top = parent_rect.top + y;
            screen_rect->right = screen_rect->left + window_width;
            screen_rect->bottom = screen_rect->top + window_height;
            last_layout_.valid = true;
            last_layout_.centered = false;
            last_layout_.widgets_enabled = false;
            last_layout_.source = source;
            last_layout_.taskbar_frame = parent_rect;
            last_layout_.task_list = anchor_rect;
            last_layout_.tray_frame = tray_rect;
            last_layout_.lyric_rect = *screen_rect;
            return true;
        }
    }

    RECT work{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    screen_rect->left = work.left + ((work.right - work.left) - kPreferredWidth) / 2;
    screen_rect->top = work.bottom - kFallbackHeight - 8;
    screen_rect->right = screen_rect->left + kPreferredWidth;
    screen_rect->bottom = screen_rect->top + kFallbackHeight;
    last_layout_.valid = true;
    last_layout_.centered = false;
    last_layout_.widgets_enabled = false;
    last_layout_.source = L"work-area-fallback";
    last_layout_.taskbar_frame = work;
    last_layout_.task_list = {};
    last_layout_.tray_frame = {};
    last_layout_.widgets_button = {};
    last_layout_.lyric_rect = *screen_rect;
    return true;
}

void TaskbarWindow::apply_window_rect(const RECT& screen_rect) {
    if (!hwnd_ || !is_valid_rect(screen_rect)) {
        return;
    }

    RECT reference_rect{};
    if (attached_ && parent_hwnd_ && IsWindow(parent_hwnd_)) {
        GetWindowRect(parent_hwnd_, &reference_rect);
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
        window_width_ = static_cast<UINT>(width);
        window_height_ = static_cast<UINT>(height);
        if (renderer_ && composition_ready_) {
            renderer_->resize(window_width_, window_height_);
        }
    }

    if (changed) {
        RedrawWindow(hwnd_, nullptr, nullptr, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN);
    }
}

void TaskbarWindow::refresh_window() {
    RECT screen_rect{};
    {
        std::scoped_lock lock(mutex_);
        compute_target_rect_locked(&screen_rect);
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

    return renderer_->render(config_, lyric_state_, window_width_, window_height_);
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


