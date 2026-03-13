#include <windows.h>

BOOL APIENTRY DllMain(HMODULE module_handle, DWORD reason, LPVOID reserved) {
    (void)module_handle;
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module_handle);
    }
    return TRUE;
}
