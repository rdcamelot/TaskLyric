#pragma once

#if defined(_WIN32)
#define TASKLYRIC_EXPORT extern "C" __declspec(dllexport)
#else
#define TASKLYRIC_EXPORT extern "C"
#endif

TASKLYRIC_EXPORT int tasklyric_initialize(const wchar_t* base_dir);
TASKLYRIC_EXPORT int tasklyric_shutdown();
TASKLYRIC_EXPORT int tasklyric_emit_event(const wchar_t* event_name, const wchar_t* payload_json);
TASKLYRIC_EXPORT int tasklyric_call_native(const wchar_t* method, const wchar_t* payload_json);
TASKLYRIC_EXPORT const wchar_t* tasklyric_get_state_json();
TASKLYRIC_EXPORT const wchar_t* tasklyric_get_runtime_script_path();
TASKLYRIC_EXPORT const wchar_t* tasklyric_take_pending_command_json();
