use std::fs::{create_dir_all, OpenOptions};
use std::io::Write;
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;
#[cfg(not(debug_assertions))]
use std::time::Instant;

use tauri::{AppHandle, Manager, State};

#[derive(Default)]
struct BackendProcess(Mutex<Option<Child>>);

impl Drop for BackendProcess {
    fn drop(&mut self) {
        if let Ok(mut child) = self.0.lock() {
            if let Some(mut child) = child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn is_port_open(host: &str, port: u16) -> bool {
    let Ok(addr) = format!("{host}:{port}").parse::<SocketAddr>() else {
        return false;
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(150)).is_ok()
}

#[cfg(not(debug_assertions))]
fn wait_for_port(host: &str, port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if is_port_open(host, port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    is_port_open(host, port)
}

fn append_log(path: PathBuf, message: &str) {
    if let Some(parent) = path.parent() {
        let _ = create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{message}");
    }
}

fn write_log(path: PathBuf, message: &str) {
    if let Some(parent) = path.parent() {
        let _ = create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(path)
    {
        let _ = writeln!(file, "{message}");
    }
}

fn path_string(result: Result<PathBuf, tauri::Error>) -> String {
    result
        .map(|path| path.to_string_lossy().to_string())
        .unwrap_or_else(|error| format!("ERROR: {error}"))
}

fn file_status(path: PathBuf) -> String {
    match std::fs::metadata(&path) {
        Ok(metadata) => format!("{} exists=true bytes={}", path.display(), metadata.len()),
        Err(error) => format!("{} exists=false error={}", path.display(), error),
    }
}

fn backend_resource_candidates(app: &AppHandle) -> Result<Vec<PathBuf>, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("failed to resolve resource dir: {error}"))?;
    Ok(vec![
        resource_dir.join("backend").join("aisync-backend.exe"),
        resource_dir
            .join("resources")
            .join("backend")
            .join("aisync-backend.exe"),
    ])
}

fn start_backend(
    app: &AppHandle,
    state: &BackendProcess,
    backend_path: PathBuf,
    host: &str,
    port: u16,
) -> Result<String, String> {
    let log_dir = app
        .path()
        .app_log_dir()
        .map_err(|error| format!("failed to resolve log dir: {error}"))?;
    create_dir_all(&log_dir).map_err(|error| format!("failed to create log dir: {error}"))?;

    append_log(
        log_dir.join("backend.last_start.txt"),
        &format!("backend candidate: {}", backend_path.display()),
    );

    if is_port_open(host, port) {
        append_log(
            log_dir.join("backend.last_start.txt"),
            &format!("port already open: {host}:{port}"),
        );
        return Ok(log_dir.to_string_lossy().to_string());
    }

    let mut guard = state
        .0
        .lock()
        .map_err(|_| "backend process lock poisoned".to_string())?;
    if let Some(child) = guard.as_mut() {
        match child.try_wait() {
            Ok(None) => return Ok(log_dir.to_string_lossy().to_string()),
            Ok(Some(_)) => {
                guard.take();
            }
            Err(error) => return Err(format!("failed to check backend process: {error}")),
        }
    }

    if !backend_path.exists() {
        return Err(format!(
            "backend executable not found: {}",
            backend_path.display()
        ));
    }

    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("backend.out.log"))
        .map_err(|error| format!("failed to open backend stdout log: {error}"))?;
    let stderr = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("backend.err.log"))
        .map_err(|error| format!("failed to open backend stderr log: {error}"))?;

    let child = Command::new(&backend_path)
        .args(["--host", host, "--port", &port.to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .map_err(|error| format!("failed to launch backend: {error}"))?;

    append_log(
        log_dir.join("backend.last_start.txt"),
        &format!("backend launched: pid={}", child.id()),
    );

    *guard = Some(child);
    Ok(log_dir.to_string_lossy().to_string())
}

#[cfg(not(debug_assertions))]
fn start_packaged_backend(app: &AppHandle) -> Result<String, String> {
    let state = app.state::<BackendProcess>();
    let mut errors = Vec::new();
    for path in backend_resource_candidates(app)? {
        match start_backend(app, &state, path.clone(), "127.0.0.1", 8000) {
            Ok(log_dir) => return Ok(log_dir),
            Err(error) => errors.push(error),
        }
    }
    Err(errors.join("; "))
}

#[tauri::command]
fn launch_backend(app: AppHandle, state: State<'_, BackendProcess>, path: String) -> Result<String, String> {
    start_backend(&app, &state, PathBuf::from(path), "127.0.0.1", 8000)
}

#[tauri::command]
fn backend_diagnostics(app: AppHandle, state: State<'_, BackendProcess>) -> String {
    backend_diagnostics_text(&app, Some(state.inner()))
}

fn backend_diagnostics_text(app: &AppHandle, state: Option<&BackendProcess>) -> String {
    let candidates = backend_resource_candidates(app)
        .unwrap_or_default()
        .into_iter()
        .map(|path| format!("{} exists={}", path.display(), path.exists()))
        .collect::<Vec<_>>()
        .join("\n");

    let managed_child = state
        .map(|state| match state.0.lock() {
            Ok(mut guard) => match guard.as_mut() {
                Some(child) => match child.try_wait() {
                    Ok(None) => format!("running pid={}", child.id()),
                    Ok(Some(status)) => format!("exited pid={} status={status}", child.id()),
                    Err(error) => format!("check_failed pid={} error={error}", child.id()),
                },
                None => "none".to_string(),
            },
            Err(_) => "lock_poisoned".to_string(),
        })
        .unwrap_or_else(|| "unavailable".to_string());

    let log_files = app
        .path()
        .app_log_dir()
        .map(|log_dir| {
            [
                file_status(log_dir.join("backend.last_start.txt")),
                file_status(log_dir.join("backend.out.log")),
                file_status(log_dir.join("backend.err.log")),
                file_status(log_dir.join("frontend.boot.log")),
            ]
            .join("\n")
        })
        .unwrap_or_else(|error| format!("failed to resolve log dir: {error}"));

    format!(
        "version=0.1.4\nlog_dir={}\napp_data_dir={}\napp_config_dir={}\nresource_dir={}\ncurrent_exe={}\nport_127.0.0.1_8000_open={}\nmanaged_backend_child={}\ncandidates:\n{}\nlogs:\n{}",
        path_string(app.path().app_log_dir()),
        path_string(app.path().app_data_dir()),
        path_string(app.path().app_config_dir()),
        path_string(app.path().resource_dir()),
        std::env::current_exe()
            .map(|path| path.to_string_lossy().to_string())
            .unwrap_or_else(|error| format!("ERROR: {error}")),
        is_port_open("127.0.0.1", 8000),
        managed_child,
        candidates,
        log_files,
    )
}

#[tauri::command]
fn frontend_diagnostics(app: AppHandle, message: String) -> Result<(), String> {
    let log_dir = app
        .path()
        .app_log_dir()
        .map_err(|error| format!("failed to resolve log dir: {error}"))?;
    append_log(log_dir.join("frontend.boot.log"), &message);
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .manage(BackendProcess::default())
        .setup(|app| {
            if let Ok(data_dir) = app.path().app_data_dir() {
                write_log(
                    data_dir.join("startup-diagnostics.txt"),
                    &backend_diagnostics_text(app.handle(), None),
                );
            }
            if let Ok(log_dir) = app.path().app_log_dir() {
                let _ = create_dir_all(&log_dir);
                write_log(log_dir.join("backend.last_start.txt"), "native setup version=0.1.4");
                write_log(log_dir.join("frontend.boot.log"), "native setup version=0.1.4");
            }
            #[cfg(debug_assertions)]
            {
                if let Ok(log_dir) = app.path().app_log_dir() {
                    append_log(
                        log_dir.join("backend.last_start.txt"),
                        "dev build: packaged backend startup skipped; expecting scripts/tauri_dev.ps1 to run Python backend",
                    );
                }
            }

            #[cfg(not(debug_assertions))]
            {
                if let Err(error) = start_packaged_backend(app.handle()) {
                    if let Ok(log_dir) = app.path().app_log_dir() {
                        let _ = create_dir_all(&log_dir);
                        append_log(log_dir.join("backend.err.log"), &error);
                        append_log(log_dir.join("backend.last_start.txt"), &format!("startup failed: {error}"));
                    }
                }
                let _ = wait_for_port("127.0.0.1", 8000, Duration::from_secs(5));
            }

            if let Ok(data_dir) = app.path().app_data_dir() {
                let state = app.state::<BackendProcess>();
                write_log(
                    data_dir.join("startup-diagnostics.txt"),
                    &backend_diagnostics_text(app.handle(), Some(state.inner())),
                );
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            launch_backend,
            backend_diagnostics,
            frontend_diagnostics
        ])
        .plugin(tauri_plugin_dialog::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
