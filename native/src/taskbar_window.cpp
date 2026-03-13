#include "tasklyric/taskbar_window.hpp"

#include <windows.h>

#include <algorithm>
#include <array>
#include <sstream>

namespace tasklyric::native {
namespace {

constexpr wchar_t kWindowClassName[] = L"TaskLyric.TaskbarWindow";
constexpr UINT kRefreshMessage = WM_APP + 1;
constexpr UINT_PTR kLayoutTimerId = 1;
constexpr int kReservedSideWidth = 280;
constexpr int kPreferredWidth = 560;
constexpr int kMinimumWidth = 220;
constexpr int kFallbackHeight = 48;
constexpr int kPaddingX = 12;
constexpr int kPaddingY = 6;

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

}  // namespace

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
    case WM_TIMER: {
        std::scoped_lock lock(self->mutex_);
        self->update_layout_locked();
        return 0;
    }
    case kRefreshMessage:
        InvalidateRect(hwnd, nullptr, TRUE);
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT paint{};
        HDC hdc = BeginPaint(hwnd, &paint);
        {
            std::scoped_lock lock(self->mutex_);
            self->paint_locked(hdc);
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
    HINSTANCE module = current_module_handle();

    WNDCLASSW window_class{};
    window_class.lpfnWndProc = &TaskbarWindow::window_proc;
    window_class.hInstance = module;
    window_class.lpszClassName = kWindowClassName;
    window_class.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    RegisterClassW(&window_class);

    HWND parent = FindWindowW(L"Shell_TrayWnd", nullptr);
    const DWORD style = parent ? (WS_CHILD | WS_VISIBLE | WS_DISABLED) : (WS_POPUP | WS_VISIBLE | WS_DISABLED);
    const DWORD ex_style = WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;

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
        if (hwnd_) {
            update_layout_locked();
        }
    }

    if (ready_event_) {
        SetEvent(ready_event_);
    }

    if (!hwnd) {
        std::scoped_lock lock(mutex_);
        running_ = false;
        return;
    }

    SetTimer(hwnd, kLayoutTimerId, 2000, nullptr);

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }

    {
        std::scoped_lock lock(mutex_);
        destroy_fonts_locked();
        hwnd_ = nullptr;
        parent_hwnd_ = nullptr;
        attached_ = false;
        running_ = false;
    }

    UnregisterClassW(kWindowClassName, module);
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
        FW_SEMIBOLD,
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

void TaskbarWindow::update_layout_locked() {
    if (!hwnd_) {
        return;
    }

    if (attached_ && parent_hwnd_ && IsWindow(parent_hwnd_)) {
        RECT client{};
        if (GetClientRect(parent_hwnd_, &client)) {
            const int width = client.right - client.left;
            const int height = client.bottom - client.top;
            const int available = std::max(kMinimumWidth, width - (kReservedSideWidth * 2));
            const int window_width = std::clamp(kPreferredWidth, kMinimumWidth, available);
            int x = (width - window_width) / 2;
            x = std::max(kReservedSideWidth, x);
            x = std::min(x, std::max(kPaddingX, width - kReservedSideWidth - window_width));
            const int window_height = std::clamp(height - 6, 32, 60);
            const int y = std::max(0, (height - window_height) / 2);
            SetWindowPos(hwnd_, HWND_TOP, x, y, window_width, window_height, SWP_NOACTIVATE | SWP_SHOWWINDOW);
            return;
        }
    }

    RECT work{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    const int x = work.left + ((work.right - work.left) - kPreferredWidth) / 2;
    const int y = work.bottom - kFallbackHeight - 8;
    SetWindowPos(hwnd_, HWND_TOPMOST, x, y, kPreferredWidth, kFallbackHeight, SWP_NOACTIVATE | SWP_SHOWWINDOW);
}

void TaskbarWindow::paint_locked(HDC hdc) {
    RECT client{};
    GetClientRect(hwnd_, &client);

    if (attached_ && parent_hwnd_ && IsWindow(parent_hwnd_)) {
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
        SetTextColor(hdc, RGB(210, 214, 220));
        DrawTextW(hdc, sub_text.c_str(), -1, &sub_rect, flags | DT_VCENTER);
    }
}

std::wstring TaskbarWindow::snapshot_json_locked() const {
    std::wostringstream stream;
    stream << L"{"
           << L"\"running\":" << (running_ ? L"true" : L"false")
           << L",\"attached\":" << (attached_ ? L"true" : L"false")
           << L",\"hasHwnd\":" << (hwnd_ ? L"true" : L"false")
           << L",\"mainText\":\"" << escape_json(lyric_state_.main_text) << L"\""
           << L",\"subText\":\"" << escape_json(lyric_state_.sub_text) << L"\""
           << L",\"playbackState\":\"" << escape_json(lyric_state_.playback_state) << L"\""
           << L",\"fontFamily\":\"" << escape_json(config_.font_family) << L"\""
           << L",\"fontSize\":" << config_.font_size
           << L"}";
    return stream.str();
}

}  // namespace tasklyric::native




