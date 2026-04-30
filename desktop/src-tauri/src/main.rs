#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{create_dir_all, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::Mutex;

/// Holds the running sidecar so we can kill it on shutdown.
struct SidecarState {
    child: Mutex<Option<CommandChild>>,
}

fn ensure_dir(p: &PathBuf) -> PathBuf {
    let _ = create_dir_all(p);
    p.clone()
}

fn log_dir() -> PathBuf {
    #[cfg(target_os = "macos")]
    {
        let mut p = dirs::home_dir().unwrap_or_else(|| PathBuf::from("/tmp"));
        p.push("Library/Logs/LABKickstart");
        ensure_dir(&p)
    }
    #[cfg(target_os = "windows")]
    {
        let mut p = dirs::data_local_dir().unwrap_or_else(|| PathBuf::from("."));
        p.push("LABKickstart\\logs");
        ensure_dir(&p)
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        let mut p = dirs::cache_dir().unwrap_or_else(|| PathBuf::from("/tmp"));
        p.push("LABKickstart");
        ensure_dir(&p)
    }
}

fn append_log(line: &str) {
    let path = log_dir().join("backend.log");
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(&path) {
        let _ = writeln!(f, "{}", line);
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState {
            child: Mutex::new(None),
        })
        .setup(|app| {
            let app_handle = app.handle().clone();

            // Dev override: skip spawning a sidecar entirely; the developer is
            // running `python -m labkickstart` themselves at LK_DEV_BACKEND_URL.
            if let Ok(dev_url) = std::env::var("LK_DEV_BACKEND_URL") {
                if let Some(window) = app_handle.get_webview_window("main") {
                    if let Ok(parsed) = tauri::Url::parse(&dev_url) {
                        let _ = window.navigate(parsed);
                    }
                }
                return Ok(());
            }

            // Resolve writable directories via Tauri's path API.
            let runs_dir = app_handle
                .path()
                .document_dir()
                .map(|p| p.join("LABKickstart").join("runs"))
                .unwrap_or_else(|_| PathBuf::from("data/runs"));
            let cache_dir = app_handle
                .path()
                .app_data_dir()
                .map(|p| p.join("lab_guides"))
                .unwrap_or_else(|_| PathBuf::from("data/lab_guides"));
            ensure_dir(&runs_dir);
            ensure_dir(&cache_dir);

            // Pass through OPENAI_API_KEY if user has it set in OS env.
            let openai_key = std::env::var("OPENAI_API_KEY").unwrap_or_default();

            let sidecar = app_handle
                .shell()
                .sidecar("lk-backend")
                .expect("failed to locate lk-backend sidecar")
                .env("LK_PORT", "0")
                .env("LK_RUNS_DIR", runs_dir.to_string_lossy().to_string())
                .env("LK_CACHE_DIR", cache_dir.to_string_lossy().to_string())
                .env("OPENAI_API_KEY", openai_key);

            let (mut rx, child) = sidecar.spawn().expect("failed to spawn sidecar");

            // Stash the child handle for shutdown.
            let state = app_handle.state::<SidecarState>();
            tauri::async_runtime::block_on(async {
                *state.child.lock().await = Some(child);
            });

            // Drain stdout/stderr; first LK_PORT line triggers WebView navigation.
            let app_for_task = app_handle.clone();
            tauri::async_runtime::spawn(async move {
                let mut navigated = false;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            let line = String::from_utf8_lossy(&bytes).to_string();
                            append_log(&format!("[stdout] {}", line.trim_end()));
                            if !navigated {
                                if let Some(rest) = line.lines().find_map(|l| {
                                    l.trim().strip_prefix("LK_PORT=").map(|s| s.to_string())
                                }) {
                                    if let Ok(port) = rest.trim().parse::<u16>() {
                                        let url = format!("http://127.0.0.1:{}/", port);
                                        let app_for_navigate = app_for_task.clone();
                                        let nav_result = app_for_task.run_on_main_thread(move || {
                                            if let Some(w) = app_for_navigate.get_webview_window("main") {
                                                if let Ok(parsed) = tauri::Url::parse(&url) {
                                                    if let Err(e) = w.navigate(parsed) {
                                                        append_log(&format!(
                                                            "[nav-error] {:?}",
                                                            e
                                                        ));
                                                    } else {
                                                        append_log(&format!(
                                                            "[nav-ok] {}",
                                                            port
                                                        ));
                                                    }
                                                } else {
                                                    append_log("[nav-error] url parse failed");
                                                }
                                            } else {
                                                append_log("[nav-error] no main window");
                                            }
                                        });
                                        if let Err(e) = nav_result {
                                            append_log(&format!(
                                                "[nav-error] run_on_main_thread: {:?}",
                                                e
                                            ));
                                        }
                                        navigated = true;
                                    }
                                }
                            }
                        }
                        CommandEvent::Stderr(bytes) => {
                            let line = String::from_utf8_lossy(&bytes).to_string();
                            append_log(&format!("[stderr] {}", line.trim_end()));
                        }
                        CommandEvent::Terminated(payload) => {
                            append_log(&format!("[terminated] code={:?}", payload.code));
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building LABKickstart")
        .run(|app_handle, event| {
            if let RunEvent::WindowEvent {
                event: WindowEvent::CloseRequested { .. },
                ..
            } = event
            {
                let state = app_handle.state::<SidecarState>();
                let _ = tauri::async_runtime::block_on(async {
                    if let Some(child) = state.child.lock().await.take() {
                        let _ = child.kill();
                    }
                });
            }
        });
}
