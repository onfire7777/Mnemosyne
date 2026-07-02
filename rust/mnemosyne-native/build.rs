fn main() {
    // With pyo3's `extension-module` feature, libpython is (correctly) not
    // linked; on macOS the cdylib must be linked with `-undefined
    // dynamic_lookup`. maturin injects this itself, but plain `cargo build`
    // (dev loop / warning lint) needs it too — this is the canonical helper
    // that `maturin new` generates.
    pyo3_build_config::add_extension_module_link_args();
}
