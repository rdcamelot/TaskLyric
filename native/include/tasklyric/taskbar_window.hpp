#pragma once

#include <windows.h>

#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "tasklyric/taskbar_locator.hpp"

namespace tasklyric::native {

class TaskbarDCompRenderer;

struct TaskbarConfig {
    std::wstring font_family = L"Microsoft YaHei UI";
    int font_size = 17;
    COLORREF text_color = RGB(248, 250, 252);
    COLORREF sub_text_color = RGB(174, 184, 197);
    COLORREF shadow_color = RGB(5, 7, 11);
    std::wstring align = L"left";
    bool debug_fill = false;
    COLORREF debug_fill_color = RGB(156, 255, 46);
    COLORREF debug_border_color = RGB(255, 59, 48);
    int debug_border_thickness = 0;
};

struct TaskbarLyricState {
    std::wstring title;
    std::wstring artist;
    std::wstring main_text;
    std::wstring sub_text;
    std::wstring playback_state = L"unknown";
    int progress_ms = 0;
};

class TaskbarWindow {
public:
    static TaskbarWindow& instance();

    TaskbarWindow() = default;
    ~TaskbarWindow();
    TaskbarWindow(const TaskbarWindow&) = delete;
    TaskbarWindow& operator=(const TaskbarWindow&) = delete;

    bool start();
    void stop();
    void update_config(const TaskbarConfig& config);
    void update_lyric(const TaskbarLyricState& state);
    std::wstring snapshot_json() const;

private:
    static LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);
    void thread_main();
    void ensure_fonts_locked();
    void destroy_fonts_locked();
    bool compute_target_rect_locked(RECT* screen_rect);
    void apply_window_rect(const RECT& screen_rect);
    void refresh_window();
    bool render_with_composition_locked();
    void paint_locked(HDC hdc);
    std::wstring snapshot_json_locked() const;

    mutable std::mutex mutex_;
    std::thread thread_;
    HWND hwnd_ = nullptr;
    HWND parent_hwnd_ = nullptr;
    DWORD thread_id_ = 0;
    HANDLE ready_event_ = nullptr;
    bool running_ = false;
    bool attached_ = false;
    bool composition_ready_ = false;
    bool composition_attempted_ = false;
    UINT window_width_ = 0;
    UINT window_height_ = 0;
    TaskbarConfig config_{};
    TaskbarLyricState lyric_state_{};
    TaskbarLayout last_layout_{};
    HFONT main_font_ = nullptr;
    HFONT sub_font_ = nullptr;
    TaskbarLocator locator_{};
    std::unique_ptr<TaskbarDCompRenderer> renderer_;
};

}  // namespace tasklyric::native

