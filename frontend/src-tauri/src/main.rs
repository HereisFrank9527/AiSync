use std::env;
use std::fs::{create_dir_all, OpenOptions};
#[cfg(not(debug_assertions))]
use std::io::Read;
use std::io::Write;
use std::net::{SocketAddr, TcpStream};
#[cfg(not(debug_assertions))]
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::Child;
#[cfg(not(debug_assertions))]
use std::process::{Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};
use std::time::Duration;
#[cfg(not(debug_assertions))]
use std::time::Instant;
#[cfg(all(windows, not(debug_assertions)))]
use std::os::windows::process::CommandExt;

use tauri::{AppHandle, Manager, State, WindowEvent};

#[derive(Default)]
struct BackendProcess {
    child: Mutex<Option<Child>>,
    endpoint: Mutex<Option<String>>,
    shutdown_requested: AtomicBool,
}

fn app_version(_: &AppHandle) -> String {
    env!("AISYNC_APP_VERSION").to_string()
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        terminate_backend(self);
    }
}

#[cfg(all(windows, not(debug_assertions)))]
fn hide_command_window(command: &mut Command) {
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(all(not(windows), not(debug_assertions)))]
fn hide_command_window(_: &mut Command) {}

fn terminate_backend(state: &BackendProcess) {
    state.shutdown_requested.store(true, Ordering::SeqCst);
    if let Ok(mut child) = state.child.lock() {
        if let Some(mut child) = child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg(not(debug_assertions))]
fn set_backend_endpoint(state: &BackendProcess, host: &str, port: u16) {
    if let Ok(mut endpoint) = state.endpoint.lock() {
        *endpoint = Some(format!("http://{host}:{port}/api"));
    }
}

fn is_port_open(host: &str, port: u16) -> bool {
    let Ok(addr) = format!("{host}:{port}").parse::<SocketAddr>() else {
        return false;
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(150)).is_ok()
}

#[cfg(not(debug_assertions))]
fn choose_backend_port(host: &str) -> Result<u16, String> {
    if let Ok(value) = env::var("AISYNC_BACKEND_PORT") {
        let port = value
            .trim()
            .parse::<u16>()
            .map_err(|error| format!("invalid AISYNC_BACKEND_PORT={value}: {error}"))?;
        if is_port_open(host, port) {
            return Err(format!("configured backend port is already in use: {host}:{port}"));
        }
        return Ok(port);
    }

    let listener = TcpListener::bind((host, 0))
        .map_err(|error| format!("failed to allocate backend port: {error}"))?;
    listener
        .local_addr()
        .map(|addr| addr.port())
        .map_err(|error| format!("failed to read backend port: {error}"))
}

#[cfg(not(debug_assertions))]
fn is_backend_healthy(host: &str, port: u16) -> bool {
    let Ok(addr) = format!("{host}:{port}").parse::<SocketAddr>() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(300)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(700)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(300)));
    let request = format!("GET /health HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

#[cfg(debug_assertions)]
fn is_backend_healthy(host: &str, port: u16) -> bool {
    is_port_open(host, port)
}

#[cfg(not(debug_assertions))]
fn wait_for_backend_health(host: &str, port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if is_backend_healthy(host, port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    is_backend_healthy(host, port)
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

fn backend_source_candidates(app: &AppHandle) -> Result<Vec<PathBuf>, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("failed to resolve resource dir: {error}"))?;
    Ok(vec![
        resource_dir.join("backend-src"),
        resource_dir.join("resources").join("backend-src"),
    ])
}

fn bundled_python_dirs(app: &AppHandle) -> Vec<PathBuf> {
    app.path()
        .resource_dir()
        .map(|resource_dir| {
            vec![
                resource_dir
                    .join("runtime")
                    .join("python"),
                resource_dir
                    .join("resources")
                    .join("runtime")
                    .join("python"),
            ]
        })
        .unwrap_or_default()
}

fn bundled_python_candidates(app: &AppHandle) -> Vec<PathBuf> {
    bundled_python_dirs(app)
        .into_iter()
        .map(|dir| dir.join("python.exe"))
        .collect()
}

#[cfg(not(debug_assertions))]
fn bundled_backend_python_candidates(app: &AppHandle) -> Vec<PathBuf> {
    bundled_python_dirs(app)
        .into_iter()
        .flat_map(|dir| [dir.join("pythonw.exe"), dir.join("python.exe")])
        .collect()
}

fn python_candidates(app: &AppHandle) -> Vec<String> {
    let mut candidates = Vec::new();
    if let Ok(venv_python) = runtime_venv_python(app) {
        candidates.push(venv_python.to_string_lossy().to_string());
    }
    if let Ok(value) = env::var("AISYNC_PYTHON") {
        if !value.trim().is_empty() {
            candidates.push(value);
        }
    }
    candidates.extend(
        bundled_python_candidates(app)
            .into_iter()
            .map(|path| path.to_string_lossy().to_string()),
    );
    candidates.push("python".to_string());
    candidates.push("py".to_string());
    candidates
}

fn runtime_venv_dir(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app
        .path()
        .app_data_dir()
        .map_err(|error| format!("failed to resolve app data dir: {error}"))?
        .join("runtime")
        .join(".venv"))
}

fn runtime_venv_python(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(runtime_venv_dir(app)?.join("Scripts").join("python.exe"))
}

#[cfg(not(debug_assertions))]
fn runtime_wheelhouse_candidates(app: &AppHandle) -> Vec<PathBuf> {
    app.path()
        .resource_dir()
        .map(|resource_dir| {
            vec![
                resource_dir.join("runtime").join("wheels"),
                resource_dir.join("resources").join("runtime").join("wheels"),
            ]
        })
        .unwrap_or_default()
}

#[cfg(not(debug_assertions))]
fn wheelhouse_has_backend(wheelhouse: &PathBuf) -> bool {
    std::fs::read_dir(wheelhouse)
        .map(|entries| {
            entries.flatten().any(|entry| {
                let file_name = entry.file_name().to_string_lossy().to_string();
                file_name.starts_with("aisync_backend-") && file_name.ends_with(".whl")
            })
        })
        .unwrap_or(false)
}

fn command_needs_path_check(program: &str) -> bool {
    program.contains('\\') || program.contains('/') || program.contains(':')
}

#[cfg(not(debug_assertions))]
fn command_available(program: &str) -> bool {
    if command_needs_path_check(program) && !PathBuf::from(program).exists() {
        return false;
    }
    let mut command = Command::new(program);
    command.arg("--version");
    command.stdin(Stdio::null());
    command.stdout(Stdio::null());
    command.stderr(Stdio::null());
    hide_command_window(&mut command);
    command.status()
        .map(|status| status.success())
        .unwrap_or(false)
}

#[cfg(not(debug_assertions))]
fn run_setup_command(
    app: &AppHandle,
    program: &str,
    args: &[String],
    cwd: Option<PathBuf>,
    label: &str,
) -> Result<(), String> {
    let log_dir = app
        .path()
        .app_log_dir()
        .map_err(|error| format!("failed to resolve log dir: {error}"))?;
    create_dir_all(&log_dir).map_err(|error| format!("failed to create log dir: {error}"))?;
    append_log(
        log_dir.join("backend.last_start.txt"),
        &format!("runtime setup [{label}]: {program} {}", args.join(" ")),
    );
    if command_needs_path_check(program) && !PathBuf::from(program).exists() {
        return Err(format!("runtime setup program not found [{label}]: {program}"));
    }

    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("backend.setup.out.log"))
        .map_err(|error| format!("failed to open setup stdout log: {error}"))?;
    let stderr = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("backend.setup.err.log"))
        .map_err(|error| format!("failed to open setup stderr log: {error}"))?;

    let mut command = Command::new(program);
    command.args(args);
    command.env("PYTHONDONTWRITEBYTECODE", "1");
    if let Some(cwd) = cwd {
        command.current_dir(cwd);
    }
    hide_command_window(&mut command);
    let status = command
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .status()
        .map_err(|error| format!("failed to run runtime setup [{label}]: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("runtime setup failed [{label}]: {status}"))
    }
}

#[cfg(not(debug_assertions))]
fn python_backend_ready(python: &PathBuf, source_dir: &PathBuf) -> bool {
    if !python.exists() {
        return false;
    }
    let mut command = Command::new(python);
    command.args(["-c", "import fastapi, uvicorn, app.cli"]);
    command.current_dir(source_dir);
    command.stdin(Stdio::null());
    command.stdout(Stdio::null());
    command.stderr(Stdio::null());
    hide_command_window(&mut command);
    command.status()
        .map(|status| status.success())
        .unwrap_or(false)
}

#[cfg(not(debug_assertions))]
fn ensure_runtime_venv(app: &AppHandle, source_dir: &PathBuf) -> Result<PathBuf, String> {
    let venv_dir = runtime_venv_dir(app)?;
    let venv_python = runtime_venv_python(app)?;
    if python_backend_ready(&venv_python, source_dir) {
        return Ok(venv_python);
    }

    let venv_python_text = venv_python.to_string_lossy().to_string();
    let bootstrap_python = python_candidates(app)
        .into_iter()
        .filter(|candidate| candidate != &venv_python_text)
        .find(|candidate| command_available(candidate))
        .ok_or_else(|| {
            "No usable Python found. Bundle runtime/python/python.exe, set AISYNC_PYTHON, or install Python on PATH.".to_string()
        })?;

    if !venv_python.exists() {
        if let Some(parent) = venv_dir.parent() {
            create_dir_all(parent).map_err(|error| format!("failed to create runtime dir: {error}"))?;
        }
        run_setup_command(
            app,
            &bootstrap_python,
            &["-m".to_string(), "venv".to_string(), venv_dir.to_string_lossy().to_string()],
            None,
            "create-venv",
        )?;
    }

    if !venv_python.exists() {
        return Err(format!("venv python was not created: {}", venv_python.display()));
    }

    let mut install_args = vec![
        "-m".to_string(),
        "pip".to_string(),
        "install".to_string(),
        "--disable-pip-version-check".to_string(),
        "--no-warn-script-location".to_string(),
    ];
    if let Some(wheelhouse) = runtime_wheelhouse_candidates(app).into_iter().find(|path| path.exists()) {
        let has_backend_wheel = wheelhouse_has_backend(&wheelhouse);
        install_args.push("--no-index".to_string());
        install_args.push("--find-links".to_string());
        install_args.push(wheelhouse.to_string_lossy().to_string());
        if has_backend_wheel {
            install_args.push("aisync-backend".to_string());
        } else {
            install_args.push(source_dir.to_string_lossy().to_string());
        }
    } else {
        install_args.push(source_dir.to_string_lossy().to_string());
    }
    run_setup_command(
        app,
        &venv_python_text,
        &install_args,
        Some(source_dir.clone()),
        "install-backend",
    )?;

    if python_backend_ready(&venv_python, source_dir) {
        Ok(venv_python)
    } else {
        Err(format!(
            "backend dependencies are still unavailable after install: {}",
            venv_python.display()
        ))
    }
}

#[cfg(not(debug_assertions))]
fn start_backend_process(
    app: &AppHandle,
    state: &BackendProcess,
    program: &str,
    args: &[String],
    cwd: Option<PathBuf>,
    host: &str,
    port: u16,
    label: &str,
) -> Result<String, String> {
    if state.shutdown_requested.load(Ordering::SeqCst) {
        return Err("backend startup cancelled because app is closing".to_string());
    }
    let log_dir = app
        .path()
        .app_log_dir()
        .map_err(|error| format!("failed to resolve log dir: {error}"))?;
    create_dir_all(&log_dir).map_err(|error| format!("failed to create log dir: {error}"))?;

    append_log(
        log_dir.join("backend.last_start.txt"),
        &format!("backend candidate [{label}]: {program} {}", args.join(" ")),
    );
    if let Some(cwd) = &cwd {
        append_log(
            log_dir.join("backend.last_start.txt"),
            &format!("backend cwd [{label}]: {}", cwd.display()),
        );
    }

    if is_backend_healthy(host, port) {
        append_log(
            log_dir.join("backend.last_start.txt"),
            &format!("backend already healthy: http://{host}:{port}/health"),
        );
        return Ok(log_dir.to_string_lossy().to_string());
    }
    if is_port_open(host, port) {
        let message = format!("port open but backend health check failed: http://{host}:{port}/health");
        append_log(log_dir.join("backend.last_start.txt"), &message);
        return Err(message);
    }

    let mut guard = state
        .child
        .lock()
        .map_err(|_| "backend process lock poisoned".to_string())?;
    if let Some(child) = guard.as_mut() {
        match child.try_wait() {
            Ok(None) => {
                set_backend_endpoint(state, host, port);
                return Ok(log_dir.to_string_lossy().to_string());
            }
            Ok(Some(_)) => {
                guard.take();
            }
            Err(error) => return Err(format!("failed to check backend process: {error}")),
        }
    }

    if command_needs_path_check(program) && !PathBuf::from(program).exists() {
        return Err(format!(
            "backend program not found [{label}]: {program}"
        ));
    }
    if let Some(cwd) = &cwd {
        if !cwd.exists() {
            return Err(format!("backend cwd not found [{label}]: {}", cwd.display()));
        }
    }
    if state.shutdown_requested.load(Ordering::SeqCst) {
        return Err("backend startup cancelled because app is closing".to_string());
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

    let mut command = Command::new(program);
    command.args(args);
    if let Some(cwd) = cwd {
        command.current_dir(cwd);
    }
    hide_command_window(&mut command);
    let child = command
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .map_err(|error| format!("failed to launch backend [{label}]: {error}"))?;

    append_log(
        log_dir.join("backend.last_start.txt"),
        &format!("backend launched: pid={} endpoint=http://{host}:{port}/api", child.id()),
    );

    *guard = Some(child);
    set_backend_endpoint(state, host, port);
    Ok(log_dir.to_string_lossy().to_string())
}

#[cfg(not(debug_assertions))]
fn start_python_backend(app: &AppHandle, host: &str, port: u16) -> Result<String, String> {
    let state = app.state::<BackendProcess>();
    let mut errors = Vec::new();
    for source_dir in backend_source_candidates(app)? {
        if !source_dir.join("app").join("cli.py").exists() {
            errors.push(format!("backend source missing: {}", source_dir.display()));
            continue;
        }
        match ensure_runtime_venv(app, &source_dir).and_then(|python| {
            let python_text = python.to_string_lossy().to_string();
            start_backend_process(
                app,
                &state,
                &python_text,
                &[
                    "-m".to_string(),
                    "app.cli".to_string(),
                    "--host".to_string(),
                    host.to_string(),
                    "--port".to_string(),
                    port.to_string(),
                ],
                Some(source_dir.clone()),
                host,
                port,
                "python-source",
            )
        }) {
            Ok(log_dir) => return Ok(log_dir),
            Err(error) => errors.push(error),
        }
    }
    Err(errors.join("; "))
}

#[cfg(not(debug_assertions))]
fn start_bundled_python_backend(app: &AppHandle, host: &str, port: u16) -> Result<String, String> {
    let state = app.state::<BackendProcess>();
    let mut errors = Vec::new();
    let bundled_pythons = bundled_backend_python_candidates(app);
    for source_dir in backend_source_candidates(app)? {
        if !source_dir.join("app").join("cli.py").exists() {
            errors.push(format!("backend source missing: {}", source_dir.display()));
            continue;
        }
        for python in &bundled_pythons {
            if !python.exists() {
                errors.push(format!("bundled python missing: {}", python.display()));
                continue;
            }
            if !python_backend_ready(python, &source_dir) {
                errors.push(format!(
                    "bundled python dependencies unavailable: {}",
                    python.display()
                ));
                continue;
            }
            let python_text = python.to_string_lossy().to_string();
            match start_backend_process(
                app,
                &state,
                &python_text,
                &[
                    "-m".to_string(),
                    "app.cli".to_string(),
                    "--host".to_string(),
                    host.to_string(),
                    "--port".to_string(),
                    port.to_string(),
                ],
                Some(source_dir.clone()),
                host,
                port,
                "bundled-python",
            ) {
                Ok(log_dir) => return Ok(log_dir),
                Err(error) => errors.push(error),
            }
        }
    }
    Err(errors.join("; "))
}

#[tauri::command]
fn backend_diagnostics(app: AppHandle, state: State<'_, BackendProcess>) -> String {
    backend_diagnostics_text(&app, Some(state.inner()))
}

#[tauri::command]
fn backend_api_base(state: State<'_, BackendProcess>) -> String {
    state
        .endpoint
        .lock()
        .ok()
        .and_then(|endpoint| endpoint.clone())
        .unwrap_or_else(|| "http://127.0.0.1:8000/api".to_string())
}

fn backend_diagnostics_text(app: &AppHandle, state: Option<&BackendProcess>) -> String {
    let source_candidates = backend_source_candidates(app)
        .unwrap_or_default()
        .into_iter()
        .map(|path| {
            format!(
                "{} exists={} app_cli={}",
                path.display(),
                path.exists(),
                path.join("app").join("cli.py").exists()
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    let python_candidates_text = python_candidates(app)
        .into_iter()
        .map(|program| {
            let exists = if command_needs_path_check(&program) {
                PathBuf::from(&program).exists().to_string()
            } else {
                "PATH".to_string()
            };
            format!("{program} exists={exists}")
        })
        .collect::<Vec<_>>()
        .join("\n");

    let managed_child = state
        .map(|state| match state.child.lock() {
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
    let backend_endpoint = state
        .and_then(|state| state.endpoint.lock().ok().and_then(|endpoint| endpoint.clone()))
        .unwrap_or_else(|| "unavailable".to_string());
    let backend_port = backend_endpoint
        .strip_prefix("http://127.0.0.1:")
        .and_then(|value| value.strip_suffix("/api"))
        .and_then(|value| value.parse::<u16>().ok());

    let log_files = app
        .path()
        .app_log_dir()
        .map(|log_dir| {
            [
                file_status(log_dir.join("backend.last_start.txt")),
                file_status(log_dir.join("backend.out.log")),
                file_status(log_dir.join("backend.err.log")),
                file_status(log_dir.join("backend.setup.out.log")),
                file_status(log_dir.join("backend.setup.err.log")),
                file_status(log_dir.join("frontend.boot.log")),
            ]
            .join("\n")
        })
        .unwrap_or_else(|error| format!("failed to resolve log dir: {error}"));

    format!(
        "version={}\nlog_dir={}\napp_data_dir={}\napp_config_dir={}\nresource_dir={}\ncurrent_exe={}\nbackend_api_base={}\nbackend_port_open={}\nbackend_health={}\nmanaged_backend_child={}\npython_candidates:\n{}\nsource_candidates:\n{}\nlogs:\n{}",
        app_version(app),
        path_string(app.path().app_log_dir()),
        path_string(app.path().app_data_dir()),
        path_string(app.path().app_config_dir()),
        path_string(app.path().resource_dir()),
        std::env::current_exe()
            .map(|path| path.to_string_lossy().to_string())
            .unwrap_or_else(|error| format!("ERROR: {error}")),
        backend_endpoint,
        backend_port
            .map(|port| is_port_open("127.0.0.1", port).to_string())
            .unwrap_or_else(|| "unavailable".to_string()),
        backend_port
            .map(|port| is_backend_healthy("127.0.0.1", port).to_string())
            .unwrap_or_else(|| "unavailable".to_string()),
        managed_child,
        python_candidates_text,
        source_candidates,
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
                let native_setup = format!("native setup version={}", app_version(app.handle()));
                write_log(log_dir.join("backend.last_start.txt"), &native_setup);
                write_log(log_dir.join("frontend.boot.log"), &native_setup);
            }
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title(&format!("AiSync {}", app_version(app.handle())));
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
                let app_handle = app.handle().clone();
                std::thread::spawn(move || {
                    let host = "127.0.0.1";
                    let started = choose_backend_port(host).and_then(|port| {
                        let state = app_handle.state::<BackendProcess>();
                        set_backend_endpoint(state.inner(), host, port);
                        append_log(
                            app_handle
                                .path()
                                .app_log_dir()
                                .unwrap_or_else(|_| PathBuf::from("."))
                                .join("backend.last_start.txt"),
                            &format!("selected backend endpoint: http://{host}:{port}/api"),
                        );
                        start_bundled_python_backend(&app_handle, host, port).or_else(|bundled_error| {
                            append_log(
                                app_handle
                                    .path()
                                    .app_log_dir()
                                    .unwrap_or_else(|_| PathBuf::from("."))
                                    .join("backend.last_start.txt"),
                                &format!("bundled python backend failed, falling back to runtime venv: {bundled_error}"),
                            );
                            start_python_backend(&app_handle, host, port)
                        })?;
                        let _ = wait_for_backend_health(host, port, Duration::from_secs(5));
                        Ok(())
                    });
                    if let Err(error) = started {
                        if let Ok(log_dir) = app_handle.path().app_log_dir() {
                            let _ = create_dir_all(&log_dir);
                            append_log(log_dir.join("backend.err.log"), &error);
                            append_log(log_dir.join("backend.last_start.txt"), &format!("startup failed: {error}"));
                        }
                    }
                    if let Ok(data_dir) = app_handle.path().app_data_dir() {
                        let state = app_handle.state::<BackendProcess>();
                        write_log(
                            data_dir.join("startup-diagnostics.txt"),
                            &backend_diagnostics_text(&app_handle, Some(state.inner())),
                        );
                    }
                });
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
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                let state = window.app_handle().state::<BackendProcess>();
                terminate_backend(state.inner());
            }
        })
        .invoke_handler(tauri::generate_handler![
            backend_api_base,
            backend_diagnostics,
            frontend_diagnostics
        ])
        .plugin(tauri_plugin_dialog::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
