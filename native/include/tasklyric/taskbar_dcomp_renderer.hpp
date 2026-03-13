#pragma once

#include <windows.h>

#include <d2d1.h>
#include <d2d1_1.h>
#include <d3d11.h>
#include <dcomp.h>
#include <dwrite.h>
#include <dxgi1_2.h>

#include <string>

namespace tasklyric::native {

struct TaskbarConfig;
struct TaskbarLyricState;

class TaskbarDCompRenderer {
public:
    TaskbarDCompRenderer() = default;
    ~TaskbarDCompRenderer();

    bool initialize(HWND hwnd);
    void shutdown();
    bool resize(UINT width, UINT height);
    bool render(const TaskbarConfig& config, const TaskbarLyricState& state, UINT width, UINT height);
    bool is_ready() const { return ready_; }
    std::wstring snapshot_json() const;

private:
    void release_device_resources();
    bool rebuild_target_bitmap();
    bool ensure_visual_tree();
    void set_failure(const wchar_t* stage, HRESULT hr);

    HWND hwnd_ = nullptr;
    bool ready_ = false;
    UINT width_ = 0;
    UINT height_ = 0;
    HRESULT last_hr_ = S_OK;
    std::wstring last_stage_ = L"idle";

    ID3D11Device* d3d_device_ = nullptr;
    ID3D11DeviceContext* d3d_context_ = nullptr;
    IDXGIDevice* dxgi_device_ = nullptr;
    IDXGIAdapter* dxgi_adapter_ = nullptr;
    IDXGIFactory2* dxgi_factory_ = nullptr;
    ID2D1Factory1* d2d_factory_ = nullptr;
    ID2D1Device* d2d_device_ = nullptr;
    ID2D1DeviceContext* d2d_context_ = nullptr;
    IDWriteFactory* dwrite_factory_ = nullptr;
    IDCompositionDevice* dcomp_device_ = nullptr;
    IDCompositionTarget* dcomp_target_ = nullptr;
    IDCompositionVisual* dcomp_visual_ = nullptr;
    IDXGISwapChain1* swap_chain_ = nullptr;
    ID2D1Bitmap1* target_bitmap_ = nullptr;
};

}  // namespace tasklyric::native
