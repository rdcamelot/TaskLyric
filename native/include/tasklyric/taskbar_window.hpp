#pragma once

#include <windows.h>

#include <mutex>
#include <string>
#include <thread>

namespace tasklyric::native {

struct TaskbarConfig {
    std::wstring font_family = L"Microsoft YaHei UI";
    int font_size = 16;
    COLORREF text_color = RGB(245, 247, 250);
    COLORREF shadow_color = RGB(20, 22, 26);
    std::wstring align = L"center";
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

    bool start();
    void stop();
    void update_config(const TaskbarConfig& config);
    void update_lyric(const TaskbarLyricState& state);
    std::wstring snapshot_json() const;

private:
    TaskbarWindow() = default;
    ~TaskbarWindow() = default;
    TaskbarWindow(const TaskbarWindow&) = delete;
    TaskbarWindow& operator=(const TaskbarWindow&) = delete;

    static LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);
    void thread_main();
    void ensure_fonts_locked();
    void destroy_fonts_locked();
    void update_layout_locked();
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
    TaskbarConfig config_{};
    TaskbarLyricState lyric_state_{};
    HFONT main_font_ = nullptr;
    HFONT sub_font_ = nullptr;
};

}  // namespace tasklyric::native
