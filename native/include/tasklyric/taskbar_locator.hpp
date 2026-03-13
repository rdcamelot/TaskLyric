#pragma once

#include <windows.h>

#include <string>

namespace tasklyric::native {

struct TaskbarLayout {
    bool valid = false;
    bool centered = false;
    bool widgets_enabled = false;
    std::wstring source = L"uninitialized";
    RECT taskbar_frame{};
    RECT task_list{};
    RECT tray_frame{};
    RECT widgets_button{};
    RECT lyric_rect{};
};

class TaskbarLocator {
public:
    TaskbarLocator() = default;
    ~TaskbarLocator();

    TaskbarLocator(const TaskbarLocator&) = delete;
    TaskbarLocator& operator=(const TaskbarLocator&) = delete;

    bool initialize(HWND taskbar_hwnd);
    TaskbarLayout query();
    void shutdown();

private:
    struct Impl;
    Impl* impl_ = nullptr;
};

}  // namespace tasklyric::native
