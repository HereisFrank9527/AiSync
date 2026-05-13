fn main() {
    println!("cargo:rerun-if-changed=tauri.conf.json");
    let config = std::fs::read_to_string("tauri.conf.json").unwrap_or_default();
    let version = config
        .split("\"version\"")
        .nth(1)
        .and_then(|tail| tail.split(':').nth(1))
        .and_then(|tail| tail.split('"').nth(1))
        .unwrap_or("0.0.0");
    println!("cargo:rustc-env=AISYNC_APP_VERSION={version}");
    tauri_build::build()
}
