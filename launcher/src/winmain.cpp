#include <windows.h>
#include <shellapi.h>

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

std::wstring quote_argument(const std::wstring& value) {
    if (value.empty()) {
        return L"\"\"";
    }
    const bool needs_quotes = value.find_first_of(L" \t\"") != std::wstring::npos;
    if (!needs_quotes) {
        return value;
    }
    std::wstring quoted;
    quoted.reserve(value.size() + 4);
    quoted.push_back(L'"');
    for (const wchar_t ch : value) {
        if (ch == L'"') {
            quoted += L"\\\"";
        } else {
            quoted.push_back(ch);
        }
    }
    quoted.push_back(L'"');
    return quoted;
}

std::optional<fs::path> current_executable_path() {
    std::wstring buffer(MAX_PATH, L'\0');
    while (true) {
        DWORD written = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
        if (written == 0) {
            return std::nullopt;
        }
        if (written < buffer.size() - 1) {
            buffer.resize(written);
            return fs::path(buffer);
        }
        buffer.resize(buffer.size() * 2);
    }
}

std::optional<fs::path> find_repo_root() {
    auto exe_path = current_executable_path();
    if (!exe_path) {
        return std::nullopt;
    }

    fs::path current = exe_path->parent_path();
    for (int depth = 0; depth < 6; ++depth) {
        if (fs::exists(current / L"launcher.pyw") && fs::exists(current / L"src" / L"netease_taskbar_lyrics" / L"launcher.py")) {
            return current;
        }
        if (!current.has_parent_path()) {
            break;
        }
        current = current.parent_path();
    }
    return std::nullopt;
}

std::optional<fs::path> search_path_for(const wchar_t* executable_name) {
    if (!executable_name || !*executable_name) {
        return std::nullopt;
    }

    std::wstring buffer(MAX_PATH, L'\0');
    while (true) {
        DWORD written = SearchPathW(nullptr, executable_name, nullptr, static_cast<DWORD>(buffer.size()), buffer.data(), nullptr);
        if (written == 0) {
            return std::nullopt;
        }
        if (written < buffer.size()) {
            buffer.resize(written);
            return fs::path(buffer);
        }
        buffer.resize(written + 1);
    }
}

std::optional<fs::path> find_python_gui_host() {
    for (const wchar_t* candidate : {L"pythonw.exe", L"python.exe", L"pyw.exe", L"py.exe"}) {
        auto path = search_path_for(candidate);
        if (path) {
            return path;
        }
    }
    return std::nullopt;
}

int show_error(const std::wstring& title, const std::wstring& message) {
    MessageBoxW(nullptr, message.c_str(), title.c_str(), MB_ICONERROR | MB_OK);
    return 1;
}

}  // namespace

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
    auto root = find_repo_root();
    if (!root) {
        return show_error(L"TaskLyric", L"Could not locate the TaskLyric project root next to tasklyric_launcher.exe.");
    }

    auto python = find_python_gui_host();
    if (!python) {
        return show_error(L"TaskLyric", L"Could not locate pythonw.exe or python.exe in PATH.");
    }

    const fs::path launcher_script = *root / L"launcher.pyw";
    if (!fs::exists(launcher_script)) {
        return show_error(L"TaskLyric", L"launcher.pyw was not found in the TaskLyric root directory.");
    }

    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    std::vector<std::wstring> arguments;
    arguments.reserve(static_cast<size_t>(argc > 1 ? argc : 1));
    arguments.push_back(launcher_script.wstring());
    for (int index = 1; index < argc; ++index) {
        arguments.emplace_back(argv[index]);
    }
    if (argv) {
        LocalFree(argv);
    }

    std::wstring command_line = quote_argument(python->wstring());
    for (const auto& argument : arguments) {
        command_line.push_back(L' ');
        command_line += quote_argument(argument);
    }

    STARTUPINFOW startup_info{};
    startup_info.cb = sizeof(startup_info);
    PROCESS_INFORMATION process_info{};
    std::wstring mutable_command_line = command_line;
    DWORD creation_flags = CREATE_NO_WINDOW;

    const BOOL ok = CreateProcessW(
        python->c_str(),
        mutable_command_line.data(),
        nullptr,
        nullptr,
        FALSE,
        creation_flags,
        nullptr,
        root->wstring().c_str(),
        &startup_info,
        &process_info
    );
    if (!ok) {
        return show_error(L"TaskLyric", L"Failed to start the TaskLyric launcher process.");
    }

    CloseHandle(process_info.hThread);
    CloseHandle(process_info.hProcess);
    return 0;
}
