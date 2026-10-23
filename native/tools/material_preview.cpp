#include "tasklyric/taskbar_dcomp_renderer.hpp"
#include "tasklyric/taskbar_window.hpp"

#include <array>
#include <cstdio>
#include <string_view>

using namespace tasklyric::native;

namespace {
struct Sample {
    HWND window = nullptr;
    TaskbarDCompRenderer renderer;
    TaskbarConfig config;
    TaskbarLyricState lyric;
    TaskbarWindowUiState ui;
    UINT width = 560;
    UINT height = 60;
};

std::array<Sample, 6> samples;
constexpr int kRowPitch = 96;
constexpr wchar_t kClass[] = L"TaskLyric.MaterialPreview";
bool smoke = false;
bool failed = false;
int frames = 0;

void draw_samples() {
    for (auto& sample : samples) {
        if (!sample.renderer.render(sample.config, sample.lyric, sample.ui, sample.width, sample.height)) {
            std::fwprintf(stderr, L"Render failed: %ls\n", sample.renderer.snapshot_json().c_str());
            failed = true;
        }
    }
}

LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    switch (message) {
    case WM_PAINT: {
        PAINTSTRUCT paint{};
        HDC dc = BeginPaint(window, &paint);
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, RGB(65, 70, 78));
        const wchar_t* labels[] = {
            L"Dark / bilingual / 560 x 60",
            L"Light / bilingual / 560 x 60",
            L"Dark / compact / hover / 300 x 60",
            L"Light / compact / pressed / 300 x 60",
            L"Dark / no controls / 220 x 60",
            L"Light / single line / 560 x 48",
        };
        for (size_t i = 0; i < samples.size(); ++i) {
            const int y = 12 + static_cast<int>(i) * kRowPitch;
            TextOutW(dc, 24, y, labels[i], static_cast<int>(wcslen(labels[i])));
            // A synthetic backdrop, not a capture of the user's desktop.
            for (int x = 0; x < 620; ++x) {
                const float t = static_cast<float>(x) / 619.0f;
                const bool light = i % 2 != 0;
                const auto mix = [t](int a, int b) { return static_cast<BYTE>(a + (b - a) * t); };
                HBRUSH brush = CreateSolidBrush(light
                    ? RGB(mix(212, 242), mix(226, 229), mix(239, 216))
                    : RGB(mix(24, 55), mix(36, 39), mix(54, 42)));
                RECT strip{24 + x, y + 25, 25 + x, y + 91};
                FillRect(dc, &strip, brush);
                DeleteObject(brush);
            }
        }
        EndPaint(window, &paint);
        return 0;
    }
    case WM_TIMER:
        if (smoke) {
            // Exercise the same renderer teardown/recreate used on taskbar resize.
            auto& sample = samples[0];
            sample.width = frames % 2 ? 560 : 300;
            sample.renderer.shutdown();
            SetWindowPos(sample.window, nullptr, 0, 0, sample.width, sample.height, SWP_NOMOVE | SWP_NOZORDER);
            if (!sample.renderer.initialize(sample.window)) {
                failed = true;
            }
            // Theme changes must rebuild cached brushes without resetting the device.
            samples[1].config.theme_mode = frames % 2 ? L"light" : L"dark";
            samples[4].config.theme_mode = frames % 2 ? L"manual" : L"dark";
            samples[5].config.debug_fill = frames % 2 != 0;
            samples[2].lyric.playback_state = L"playing";
            samples[2].lyric.progress_ms = frames * 500;
        }
        draw_samples();
        if (smoke && ++frames >= 8) {
            DestroyWindow(window);
        }
        return 0;
    case WM_CLOSE:
        DestroyWindow(window);
        return 0;
    case WM_DESTROY:
        KillTimer(window, 1);
        PostQuitMessage(failed ? 1 : 0);
        return 0;
    default:
        return DefWindowProcW(window, message, wparam, lparam);
    }
}
}  // namespace

int main(int argc, char** argv) {
    smoke = argc > 1 && std::string_view(argv[1]) == "--smoke";
    SetProcessDPIAware();
    const HRESULT com_result = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(com_result)) {
        return 1;
    }
    const HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSW cls{};
    cls.hInstance = instance;
    cls.lpfnWndProc = window_proc;
    cls.lpszClassName = kClass;
    cls.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
    cls.hCursor = LoadCursor(nullptr, IDC_ARROW);
    if (!RegisterClassW(&cls)) {
        CoUninitialize();
        return 1;
    }
    WNDCLASSW surface_class{};
    surface_class.hInstance = instance;
    surface_class.lpfnWndProc = DefWindowProcW;
    surface_class.lpszClassName = L"TaskLyric.MaterialPreview.Surface";
    if (!RegisterClassW(&surface_class)) {
        CoUninitialize();
        return 1;
    }
    HWND parent = CreateWindowExW(0, kClass, L"TaskLyric material preview - synthetic backgrounds", WS_OVERLAPPEDWINDOW,
        160, 100, 690, 640, nullptr, nullptr, instance, nullptr);
    if (!parent) {
        CoUninitialize();
        return 1;
    }
    for (size_t i = 0; i < samples.size(); ++i) {
        auto& sample = samples[i];
        sample.config.theme_mode = i % 2 ? L"light" : L"dark";
        sample.lyric.main_text = L"Light moves softly through the glass";
        sample.lyric.sub_text = L"\u5149\u5f71\u6d41\u52a8\uff0c\u6b4c\u8bcd\u6e05\u6670\u53ef\u89c1";
        sample.lyric.playback_state = L"paused";
        if (i == 2 || i == 3) {
            sample.width = 300;
            sample.lyric.main_text = L"Soft light";
        }
        if (i == 2) sample.ui.hot_action = TaskbarControlAction::toggle_playback;
        if (i == 3) sample.ui.pressed_action = TaskbarControlAction::toggle_playback;
        if (i == 4) sample.width = 220;
        if (i == 5) {
            sample.height = 48;
            sample.lyric.sub_text.clear();
        }
        sample.window = CreateWindowExW(WS_EX_NOREDIRECTIONBITMAP, surface_class.lpszClassName, L"", WS_CHILD | WS_VISIBLE,
            32, 40 + static_cast<int>(i) * kRowPitch, sample.width, sample.height, parent, nullptr, instance, nullptr);
        if (!sample.window || !sample.renderer.initialize(sample.window)) {
            failed = true;
            break;
        }
    }
    if (!failed) {
        ShowWindow(parent, SW_SHOWNOACTIVATE);
        UpdateWindow(parent);
        if (!SetTimer(parent, 1, 500, nullptr)) {
            failed = true;
            DestroyWindow(parent);
        } else {
            MSG message{};
            BOOL result = 0;
            while ((result = GetMessageW(&message, nullptr, 0, 0)) > 0) {
                TranslateMessage(&message);
                DispatchMessageW(&message);
            }
            if (result == -1) {
                failed = true;
                DestroyWindow(parent);
            }
        }
    } else {
        DestroyWindow(parent);
    }
    for (auto& sample : samples) sample.renderer.shutdown();
    CoUninitialize();
    std::printf("Material preview: %s (%d resize cycles, 6 samples)\n", failed ? "FAIL" : "PASS", frames);
    return failed ? 1 : 0;
}
