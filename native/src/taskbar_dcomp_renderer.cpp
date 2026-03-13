#include "tasklyric/taskbar_dcomp_renderer.hpp"

#include "tasklyric/taskbar_window.hpp"

#include <algorithm>
#include <sstream>

namespace tasklyric::native {
namespace {

template <typename T>
void safe_release(T*& pointer) {
    if (pointer) {
        pointer->Release();
        pointer = nullptr;
    }
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

D2D1_COLOR_F to_d2d_color(COLORREF color, float alpha = 1.0f) {
    return D2D1_COLOR_F{
        static_cast<float>(GetRValue(color)) / 255.0f,
        static_cast<float>(GetGValue(color)) / 255.0f,
        static_cast<float>(GetBValue(color)) / 255.0f,
        alpha,
    };
}

DWRITE_TEXT_ALIGNMENT to_text_alignment(std::wstring_view align) {
    if (align == L"left") {
        return DWRITE_TEXT_ALIGNMENT_LEADING;
    }
    if (align == L"right") {
        return DWRITE_TEXT_ALIGNMENT_TRAILING;
    }
    return DWRITE_TEXT_ALIGNMENT_CENTER;
}

}  // namespace

TaskbarDCompRenderer::~TaskbarDCompRenderer() {
    shutdown();
}

bool TaskbarDCompRenderer::initialize(HWND hwnd) {
    if (ready_) {
        return true;
    }

    hwnd_ = hwnd;
    set_failure(L"initialize", S_OK);

    UINT creation_flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
    D3D_FEATURE_LEVEL feature_level = D3D_FEATURE_LEVEL_11_0;
    const D3D_FEATURE_LEVEL levels[] = {
        D3D_FEATURE_LEVEL_11_1,
        D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_1,
        D3D_FEATURE_LEVEL_10_0,
    };
    const UINT level_count = static_cast<UINT>(sizeof(levels) / sizeof(levels[0]));

    HRESULT hr = D3D11CreateDevice(
        nullptr,
        D3D_DRIVER_TYPE_HARDWARE,
        nullptr,
        creation_flags,
        levels,
        level_count,
        D3D11_SDK_VERSION,
        &d3d_device_,
        &feature_level,
        &d3d_context_
    );
    if (FAILED(hr)) {
        hr = D3D11CreateDevice(
            nullptr,
            D3D_DRIVER_TYPE_WARP,
            nullptr,
            creation_flags,
            levels,
            level_count,
            D3D11_SDK_VERSION,
            &d3d_device_,
            &feature_level,
            &d3d_context_
        );
    }
    if (FAILED(hr)) {
        set_failure(L"D3D11CreateDevice", hr);
        shutdown();
        return false;
    }

    hr = d3d_device_->QueryInterface(__uuidof(IDXGIDevice), reinterpret_cast<void**>(&dxgi_device_));
    if (FAILED(hr)) {
        set_failure(L"QueryInterface(IDXGIDevice)", hr);
        shutdown();
        return false;
    }

    hr = dxgi_device_->GetAdapter(&dxgi_adapter_);
    if (FAILED(hr)) {
        set_failure(L"IDXGIDevice::GetAdapter", hr);
        shutdown();
        return false;
    }

    hr = dxgi_adapter_->GetParent(__uuidof(IDXGIFactory2), reinterpret_cast<void**>(&dxgi_factory_));
    if (FAILED(hr)) {
        set_failure(L"IDXGIAdapter::GetParent", hr);
        shutdown();
        return false;
    }

    D2D1_FACTORY_OPTIONS factory_options{};
    hr = D2D1CreateFactory(
        D2D1_FACTORY_TYPE_SINGLE_THREADED,
        __uuidof(ID2D1Factory1),
        &factory_options,
        reinterpret_cast<void**>(&d2d_factory_)
    );
    if (FAILED(hr)) {
        set_failure(L"D2D1CreateFactory", hr);
        shutdown();
        return false;
    }

    hr = d2d_factory_->CreateDevice(dxgi_device_, &d2d_device_);
    if (FAILED(hr)) {
        set_failure(L"ID2D1Factory1::CreateDevice", hr);
        shutdown();
        return false;
    }

    hr = d2d_device_->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, &d2d_context_);
    if (FAILED(hr)) {
        set_failure(L"ID2D1Device::CreateDeviceContext", hr);
        shutdown();
        return false;
    }

    hr = DWriteCreateFactory(
        DWRITE_FACTORY_TYPE_SHARED,
        __uuidof(IDWriteFactory),
        reinterpret_cast<IUnknown**>(&dwrite_factory_)
    );
    if (FAILED(hr)) {
        set_failure(L"DWriteCreateFactory", hr);
        shutdown();
        return false;
    }

    hr = DCompositionCreateDevice(
        dxgi_device_,
        __uuidof(IDCompositionDevice),
        reinterpret_cast<void**>(&dcomp_device_)
    );
    if (FAILED(hr)) {
        set_failure(L"DCompositionCreateDevice", hr);
        shutdown();
        return false;
    }

    if (!ensure_visual_tree()) {
        shutdown();
        return false;
    }

    ready_ = true;
    last_stage_ = L"ready";
    last_hr_ = S_OK;
    return true;
}

void TaskbarDCompRenderer::shutdown() {
    ready_ = false;
    width_ = 0;
    height_ = 0;

    if (dcomp_target_) {
        dcomp_target_->SetRoot(nullptr);
    }

    release_device_resources();
    hwnd_ = nullptr;
}

bool TaskbarDCompRenderer::resize(UINT width, UINT height) {
    if (!ready_ || width == 0 || height == 0) {
        return false;
    }

    if (swap_chain_ && width == width_ && height == height_ && target_bitmap_) {
        return true;
    }

    safe_release(target_bitmap_);

    HRESULT hr = S_OK;
    if (!swap_chain_) {
        DXGI_SWAP_CHAIN_DESC1 desc{};
        desc.Width = width;
        desc.Height = height;
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.Stereo = FALSE;
        desc.SampleDesc.Count = 1;
        desc.SampleDesc.Quality = 0;
        desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount = 2;
        desc.Scaling = DXGI_SCALING_STRETCH;
        desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
        desc.AlphaMode = DXGI_ALPHA_MODE_PREMULTIPLIED;
        desc.Flags = 0;

        hr = dxgi_factory_->CreateSwapChainForComposition(d3d_device_, &desc, nullptr, &swap_chain_);
        if (FAILED(hr)) {
            set_failure(L"CreateSwapChainForComposition", hr);
            return false;
        }

        hr = dcomp_visual_->SetContent(swap_chain_);
        if (FAILED(hr)) {
            set_failure(L"IDCompositionVisual::SetContent", hr);
            return false;
        }
    } else {
        hr = swap_chain_->ResizeBuffers(0, width, height, DXGI_FORMAT_UNKNOWN, 0);
        if (FAILED(hr)) {
            set_failure(L"IDXGISwapChain1::ResizeBuffers", hr);
            return false;
        }
    }

    width_ = width;
    height_ = height;

    if (!rebuild_target_bitmap()) {
        return false;
    }

    hr = dcomp_device_->Commit();
    if (FAILED(hr)) {
        set_failure(L"IDCompositionDevice::Commit", hr);
        return false;
    }

    return true;
}

bool TaskbarDCompRenderer::render(const TaskbarConfig& config, const TaskbarLyricState& state, UINT width, UINT height) {
    if (!ready_ || !resize(width, height) || !target_bitmap_) {
        return false;
    }

    IDWriteTextFormat* main_format = nullptr;
    IDWriteTextFormat* sub_format = nullptr;
    ID2D1SolidColorBrush* main_brush = nullptr;
    ID2D1SolidColorBrush* sub_brush = nullptr;
    ID2D1SolidColorBrush* shadow_brush = nullptr;
    ID2D1SolidColorBrush* glow_brush = nullptr;
    ID2D1SolidColorBrush* fill_brush = nullptr;
    ID2D1SolidColorBrush* border_brush = nullptr;
    IDWriteInlineObject* trimming_sign = nullptr;

    bool success = false;
    HRESULT hr = S_OK;

    const std::wstring main_text = state.main_text.empty() ? state.title : state.main_text;
    const std::wstring sub_text = state.sub_text.empty() ? state.artist : state.sub_text;
    const bool has_sub_text = !sub_text.empty();
    const bool is_paused = state.playback_state == L"paused";
    const DWRITE_TEXT_ALIGNMENT alignment = to_text_alignment(config.align);
    const FLOAT main_font_size = static_cast<FLOAT>(std::clamp(config.font_size, 12, 34));
    const FLOAT sub_font_size = static_cast<FLOAT>(std::max(11, config.font_size - 5));
    const float width_f = static_cast<float>(width);
    const float height_f = static_cast<float>(height);
    const float padding_x = 16.0f;
    const float padding_y = has_sub_text ? 6.0f : 5.0f;
    const float main_top = has_sub_text ? (padding_y - 0.5f) : std::max(3.0f, (height_f - (main_font_size + 8.0f)) * 0.5f - 0.5f);
    const float main_bottom = has_sub_text ? (main_top + main_font_size + 6.0f) : (main_top + main_font_size + 8.0f);
    const D2D1_MATRIX_3X2_F identity = {1.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f};
    const D2D1_COLOR_F transparent = D2D1_COLOR_F{0.0f, 0.0f, 0.0f, 0.0f};
    const D2D1_RECT_F full_rect = {0.0f, 0.0f, width_f, height_f};
    const D2D1_RECT_F main_rect = {
        padding_x,
        main_top,
        width_f - padding_x,
        main_bottom,
    };
    const D2D1_RECT_F sub_rect = {
        padding_x,
        has_sub_text ? (main_bottom - 0.5f) : 0.0f,
        width_f - padding_x,
        has_sub_text ? (height_f - padding_y + 1.0f) : 0.0f,
    };
    const D2D1_RECT_F main_glow = {
        main_rect.left,
        main_rect.top + 2.0f,
        main_rect.right,
        main_rect.bottom + 2.0f,
    };
    const D2D1_RECT_F main_shadow = {
        main_rect.left,
        main_rect.top + 1.0f,
        main_rect.right,
        main_rect.bottom + 1.0f,
    };
    const D2D1_RECT_F sub_glow = {
        sub_rect.left,
        sub_rect.top + 1.5f,
        sub_rect.right,
        sub_rect.bottom + 1.5f,
    };
    const D2D1_RECT_F sub_shadow = {
        sub_rect.left,
        sub_rect.top + 0.75f,
        sub_rect.right,
        sub_rect.bottom + 0.75f,
    };

    do {
        hr = dwrite_factory_->CreateTextFormat(
            config.font_family.c_str(),
            nullptr,
            DWRITE_FONT_WEIGHT_MEDIUM,
            DWRITE_FONT_STYLE_NORMAL,
            DWRITE_FONT_STRETCH_NORMAL,
            main_font_size,
            L"zh-CN",
            &main_format
        );
        if (FAILED(hr)) {
            set_failure(L"CreateTextFormat(main)", hr);
            break;
        }

        hr = dwrite_factory_->CreateTextFormat(
            config.font_family.c_str(),
            nullptr,
            DWRITE_FONT_WEIGHT_NORMAL,
            DWRITE_FONT_STYLE_NORMAL,
            DWRITE_FONT_STRETCH_NORMAL,
            sub_font_size,
            L"zh-CN",
            &sub_format
        );
        if (FAILED(hr)) {
            set_failure(L"CreateTextFormat(sub)", hr);
            break;
        }

        main_format->SetTextAlignment(alignment);
        main_format->SetParagraphAlignment(DWRITE_PARAGRAPH_ALIGNMENT_NEAR);
        main_format->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
        sub_format->SetTextAlignment(alignment);
        sub_format->SetParagraphAlignment(DWRITE_PARAGRAPH_ALIGNMENT_NEAR);
        sub_format->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);

        DWRITE_TRIMMING trimming{};
        trimming.granularity = DWRITE_TRIMMING_GRANULARITY_CHARACTER;
        trimming.delimiter = 0;
        trimming.delimiterCount = 0;
        if (SUCCEEDED(dwrite_factory_->CreateEllipsisTrimmingSign(main_format, &trimming_sign)) && trimming_sign) {
            main_format->SetTrimming(&trimming, trimming_sign);
            sub_format->SetTrimming(&trimming, trimming_sign);
        }

        hr = d2d_context_->CreateSolidColorBrush(to_d2d_color(config.text_color, is_paused ? 0.78f : 0.98f), &main_brush);
        if (FAILED(hr)) {
            set_failure(L"CreateSolidColorBrush(main)", hr);
            break;
        }
        hr = d2d_context_->CreateSolidColorBrush(to_d2d_color(config.sub_text_color, is_paused ? 0.56f : 0.88f), &sub_brush);
        if (FAILED(hr)) {
            set_failure(L"CreateSolidColorBrush(sub)", hr);
            break;
        }
        hr = d2d_context_->CreateSolidColorBrush(to_d2d_color(config.shadow_color, 0.62f), &shadow_brush);
        if (FAILED(hr)) {
            set_failure(L"CreateSolidColorBrush(shadow)", hr);
            break;
        }
        hr = d2d_context_->CreateSolidColorBrush(to_d2d_color(config.shadow_color, 0.22f), &glow_brush);
        if (FAILED(hr)) {
            set_failure(L"CreateSolidColorBrush(glow)", hr);
            break;
        }
        if (config.debug_fill) {
            hr = d2d_context_->CreateSolidColorBrush(to_d2d_color(config.debug_fill_color, 0.95f), &fill_brush);
            if (FAILED(hr)) {
                set_failure(L"CreateSolidColorBrush(fill)", hr);
                break;
            }
        }
        if (config.debug_border_thickness > 0) {
            hr = d2d_context_->CreateSolidColorBrush(to_d2d_color(config.debug_border_color), &border_brush);
            if (FAILED(hr)) {
                set_failure(L"CreateSolidColorBrush(border)", hr);
                break;
            }
        }

        d2d_context_->SetTarget(target_bitmap_);
        d2d_context_->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
        d2d_context_->BeginDraw();
        d2d_context_->SetTransform(identity);
        d2d_context_->Clear(&transparent);

        if (fill_brush) {
            d2d_context_->FillRectangle(&full_rect, fill_brush);
        }

        if (!main_text.empty()) {
            d2d_context_->DrawText(
                main_text.c_str(),
                static_cast<UINT32>(main_text.size()),
                main_format,
                &main_glow,
                glow_brush,
                D2D1_DRAW_TEXT_OPTIONS_CLIP,
                DWRITE_MEASURING_MODE_NATURAL
            );
            d2d_context_->DrawText(
                main_text.c_str(),
                static_cast<UINT32>(main_text.size()),
                main_format,
                &main_shadow,
                shadow_brush,
                D2D1_DRAW_TEXT_OPTIONS_CLIP,
                DWRITE_MEASURING_MODE_NATURAL
            );
            d2d_context_->DrawText(
                main_text.c_str(),
                static_cast<UINT32>(main_text.size()),
                main_format,
                &main_rect,
                main_brush,
                D2D1_DRAW_TEXT_OPTIONS_CLIP,
                DWRITE_MEASURING_MODE_NATURAL
            );
        }

        if (has_sub_text) {
            d2d_context_->DrawText(
                sub_text.c_str(),
                static_cast<UINT32>(sub_text.size()),
                sub_format,
                &sub_glow,
                glow_brush,
                D2D1_DRAW_TEXT_OPTIONS_CLIP,
                DWRITE_MEASURING_MODE_NATURAL
            );
            d2d_context_->DrawText(
                sub_text.c_str(),
                static_cast<UINT32>(sub_text.size()),
                sub_format,
                &sub_shadow,
                shadow_brush,
                D2D1_DRAW_TEXT_OPTIONS_CLIP,
                DWRITE_MEASURING_MODE_NATURAL
            );
            d2d_context_->DrawText(
                sub_text.c_str(),
                static_cast<UINT32>(sub_text.size()),
                sub_format,
                &sub_rect,
                sub_brush,
                D2D1_DRAW_TEXT_OPTIONS_CLIP,
                DWRITE_MEASURING_MODE_NATURAL
            );
        }

        if (border_brush) {
            d2d_context_->DrawRectangle(&full_rect, border_brush, static_cast<FLOAT>(config.debug_border_thickness), nullptr);
        }

        hr = d2d_context_->EndDraw();
        if (FAILED(hr)) {
            set_failure(L"ID2D1DeviceContext::EndDraw", hr);
            break;
        }

        hr = swap_chain_->Present(1, 0);
        if (FAILED(hr)) {
            set_failure(L"IDXGISwapChain1::Present", hr);
            break;
        }

        hr = dcomp_device_->Commit();
        if (FAILED(hr)) {
            set_failure(L"IDCompositionDevice::Commit(render)", hr);
            break;
        }

        success = true;
    } while (false);

    safe_release(trimming_sign);
    safe_release(border_brush);
    safe_release(fill_brush);
    safe_release(glow_brush);
    safe_release(shadow_brush);
    safe_release(sub_brush);
    safe_release(main_brush);
    safe_release(sub_format);
    safe_release(main_format);

    if (success) {
        last_stage_ = L"rendered";
        last_hr_ = S_OK;
    }
    return success;
}
std::wstring TaskbarDCompRenderer::snapshot_json() const {
    std::wostringstream stream;
    stream << L"{"
           << L"\"ready\":" << (ready_ ? L"true" : L"false")
           << L",\"stage\":\"" << escape_json(last_stage_) << L"\""
           << L",\"lastHr\":" << static_cast<unsigned long>(last_hr_)
           << L",\"size\":[" << width_ << L"," << height_ << L"]"
           << L"}";
    return stream.str();
}

void TaskbarDCompRenderer::release_device_resources() {
    safe_release(target_bitmap_);
    safe_release(swap_chain_);
    safe_release(dcomp_visual_);
    safe_release(dcomp_target_);
    safe_release(dcomp_device_);
    safe_release(dwrite_factory_);
    safe_release(d2d_context_);
    safe_release(d2d_device_);
    safe_release(d2d_factory_);
    safe_release(dxgi_factory_);
    safe_release(dxgi_adapter_);
    safe_release(dxgi_device_);
    safe_release(d3d_context_);
    safe_release(d3d_device_);
}

bool TaskbarDCompRenderer::rebuild_target_bitmap() {
    safe_release(target_bitmap_);

    IDXGISurface* surface = nullptr;
    HRESULT hr = swap_chain_->GetBuffer(0, __uuidof(IDXGISurface), reinterpret_cast<void**>(&surface));
    if (FAILED(hr)) {
        set_failure(L"IDXGISwapChain1::GetBuffer", hr);
        return false;
    }

    D2D1_BITMAP_PROPERTIES1 properties{};
    properties.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    properties.pixelFormat.alphaMode = D2D1_ALPHA_MODE_PREMULTIPLIED;
    properties.dpiX = 96.0f;
    properties.dpiY = 96.0f;
    properties.bitmapOptions = D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;

    hr = d2d_context_->CreateBitmapFromDxgiSurface(surface, &properties, &target_bitmap_);
    safe_release(surface);
    if (FAILED(hr)) {
        set_failure(L"CreateBitmapFromDxgiSurface", hr);
        return false;
    }

    d2d_context_->SetTarget(target_bitmap_);
    return true;
}

bool TaskbarDCompRenderer::ensure_visual_tree() {
    HRESULT hr = dcomp_device_->CreateTargetForHwnd(hwnd_, FALSE, &dcomp_target_);
    if (FAILED(hr)) {
        set_failure(L"CreateTargetForHwnd", hr);
        return false;
    }

    hr = dcomp_device_->CreateVisual(&dcomp_visual_);
    if (FAILED(hr)) {
        set_failure(L"CreateVisual", hr);
        return false;
    }

    hr = dcomp_target_->SetRoot(dcomp_visual_);
    if (FAILED(hr)) {
        set_failure(L"SetRoot", hr);
        return false;
    }

    hr = dcomp_device_->Commit();
    if (FAILED(hr)) {
        set_failure(L"Commit(root)", hr);
        return false;
    }

    return true;
}

void TaskbarDCompRenderer::set_failure(const wchar_t* stage, HRESULT hr) {
    last_stage_ = stage ? stage : L"unknown";
    last_hr_ = hr;
}

}  // namespace tasklyric::native




